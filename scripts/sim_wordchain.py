"""Simula la lógica de WordChainGame de `bot.py` sin Discord. Usa la clase directamente importándola desde bot.py."""
import asyncio
import random
from bot import WordChainGame

async def simulate():
    # crear una instancia con None channel (no usado en la simulación)
    game = WordChainGame(channel=None, starter=None, turn_timeout=1)
    # add players
    players = [1111, 2222, 3333]
    for p in players:
        game.add_player(p)
    game.started = True
    # set current word
    game.current_word = 'start'
    # simulate some plays
    moves = ['tree', 'egg', 'goblin', 'night', 'tiger', 'rat']
    # randomize moves per player
    for i in range(10):
        uid = game.next_player_id()
        if uid is None:
            break
        word = random.choice(moves)
        accepted, msg = game.play_word(uid, word)
        print(f'Player {uid} played {word} ->', 'ACCEPTED' if accepted else 'REJECTED', '-', msg)
        if len(game.alive_players()) <= 1:
            break
    print('Alive players at end:', game.alive_players())

if __name__ == '__main__':
    asyncio.run(simulate())
