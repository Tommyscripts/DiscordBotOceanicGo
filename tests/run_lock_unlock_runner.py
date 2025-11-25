import asyncio
import time
import sys
import os

# Instead of importing full bot (which depends on discord.py), extract the
# lock/unlock helpers from bot.py source and exec them into a local namespace
# with minimal 'discord' shims so we can test them quickly.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
BOT_PY = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bot.py')
with open(BOT_PY, 'r') as f:
    src = f.read()

# find the helper block we injected in bot.py (between _gather_original_overwrites
# and apply_unlock_channel end). We'll extract from the start of _gather to the
# end of apply_unlock_channel.
start_marker = 'async def _gather_original_overwrites'
end_marker = 'async def apply_unlock_channel'
start = src.find(start_marker)
if start == -1:
    print('Failed to locate helper functions in bot.py')
    sys.exit(1)
# find boundary before the next top-level decorator @bot.event to avoid importing extra code
boundary = src.find('\n\n@bot.event', start)
if boundary == -1:
    # fallback: take until end
    snippet = 'from __future__ import annotations\n' + src[start:]
else:
    snippet = 'from __future__ import annotations\n' + src[start:boundary]

# Prepare a namespace with minimal discord shims
import types
discord = types.SimpleNamespace()

class PermissionOverwrite:
    def __init__(self, view_channel=None, send_messages=None):
        self.view_channel = view_channel
        self.send_messages = send_messages

# Fake types used by the extracted helpers (so isinstance checks behave)
class FakePerms:
    def __init__(self, administrator=False, manage_guild=False):
        self.administrator = administrator
        self.manage_guild = manage_guild

class FakeRole:
    def __init__(self, id_, perms=None, name=None):
        self.id = id_
        self.permissions = perms or FakePerms()
        self.name = name or f"role-{id_}"

    def __repr__(self):
        return f"<FakeRole {self.id}>"

class FakeMember:
    def __init__(self, id_, roles=None):
        self.id = id_
        self.roles = roles or []

    def __repr__(self):
        return f"<FakeMember {self.id}>"

class FakeGuild:
    def __init__(self, roles, me):
        self.roles = roles
        self.default_role = roles[0]
        self.me = me

    def get_role(self, id_):
        for r in self.roles:
            if r.id == id_:
                return r
        return None

class FakeOverwrite:
    def __init__(self, view_channel=None, send_messages=None):
        self.view_channel = view_channel
        self.send_messages = send_messages

class FakeChannel:
    def __init__(self, id_, guild, overwrites=None):
        self.id = id_
        self.guild = guild
        # store overwrites mapping: target -> FakeOverwrite
        self._overwrites = overwrites or {}
        # expose property like discord.py
        self.overwrites = self._overwrites
        self.edited = False

    async def edit(self, overwrites=None):
        # emulate small latency per edit
        await asyncio.sleep(0.01)
        # store a shallow copy
        self._overwrites = dict(overwrites or {})
        self.overwrites = self._overwrites
        self.edited = True

    async def set_permissions(self, target, overwrite=None):
        await asyncio.sleep(0.01)
        if overwrite is None:
            # remove
            self._overwrites.pop(target, None)
        else:
            self._overwrites[target] = overwrite
        self.overwrites = self._overwrites

    async def send(self, text):
        # emulate network send
        await asyncio.sleep(0.005)
        return

discord.PermissionOverwrite = PermissionOverwrite
discord.Role = FakeRole
discord.Member = FakeMember
discord.User = FakeMember
discord.abc = types.SimpleNamespace(Snowflake=object)

# prepare globals for exec
glb = {
    'discord': discord,
    'asyncio': asyncio,
    'permission_op_lock': asyncio.Lock(),
    'locked_channels': {},
}

# Make our Fake types available to the helper code (so isinstance checks work)
discord.Role = FakeRole
discord.Member = FakeMember
discord.User = FakeMember
glb['discord'] = discord

# define FakeRole and FakeMember in this namespace so isinstance checks pass
glb['FakeRole'] = None
glb['FakeMember'] = None

try:
    exec(snippet, glb)
except Exception as e:
    print('Failed to exec helpers from bot.py:', e)
    sys.exit(1)

apply_lock_channel = glb.get('apply_lock_channel')
apply_unlock_channel = glb.get('apply_unlock_channel')
locked_channels = glb.get('locked_channels')

async def run_test():
    # Build fake guild with 50 roles
    roles = [FakeRole(i) for i in range(50)]
    # make role 5 the staff role
    staff_id = 5
    # bot member
    bot_member = FakeMember(9999)
    guild = FakeGuild(roles=roles, me=bot_member)

    # Channel has only overwrites for 4 targets: @everyone (role 0), staff role (5), role 10, and bot
    overwrites = {
        roles[0]: FakeOverwrite(view_channel=True, send_messages=True),
        roles[5]: FakeOverwrite(view_channel=True, send_messages=True),
        roles[10]: FakeOverwrite(view_channel=True, send_messages=True),
        bot_member: FakeOverwrite(view_channel=True, send_messages=True),
    }
    ch = FakeChannel(id_=12345, guild=guild, overwrites=overwrites)

    print("Starting lock test: guild roles=50, channel overwrites=4")
    start = time.perf_counter()
    try:
        await apply_lock_channel(ch, guild, staff_role_id=staff_id)
    except Exception as e:
        print("apply_lock_channel raised:", e)
        sys.exit(2)
    elapsed_lock = time.perf_counter() - start
    print(f"Lock elapsed: {elapsed_lock:.4f}s")

    # verify @everyone denied
    everyone_ow = ch.overwrites.get(roles[0])
    if not everyone_ow or everyone_ow.send_messages is not False:
        print("ERROR: @everyone not denied")
        sys.exit(3)
    # staff allowed
    staff_ow = ch.overwrites.get(roles[5])
    if not staff_ow or staff_ow.send_messages is not True:
        print("ERROR: staff not allowed")
        sys.exit(4)
    # role10 denied
    r10_ow = ch.overwrites.get(roles[10])
    if not r10_ow or r10_ow.send_messages is not False:
        print("ERROR: role10 not denied")
        sys.exit(5)

    if ch.id not in locked_channels:
        print("ERROR: locked state not saved")
        sys.exit(6)

    # Unlock
    start = time.perf_counter()
    try:
        await apply_unlock_channel(ch)
    except Exception as e:
        print("apply_unlock_channel raised:", e)
        sys.exit(7)
    elapsed_unlock = time.perf_counter() - start
    print(f"Unlock elapsed: {elapsed_unlock:.4f}s")

    # Confirm restored
    if ch.id in locked_channels:
        print("ERROR: locked state still present after unlock")
        sys.exit(8)
    # role10 should be back to True
    r10_after = ch.overwrites.get(roles[10])
    if not r10_after or r10_after.send_messages is not True:
        print("ERROR: role10 not restored to True")
        sys.exit(9)

    print("All checks passed.")
    # success
    print(f"Timings: lock={elapsed_lock:.4f}s unlock={elapsed_unlock:.4f}s")
    # enforce threshold
    if elapsed_lock > 3.0 or elapsed_unlock > 3.0:
        print("WARNING: one of operations exceeded threshold of 3s")
        sys.exit(10)

if __name__ == '__main__':
    asyncio.run(run_test())
