# Custom Wheels - Guía de Uso

## 🎡 ¿Qué son las Custom Wheels?

Las Custom Wheels (Ruletas Personalizadas) permiten a cada servidor crear su propia ruleta con opciones completamente personalizadas. A diferencia de `/wheels` (que usa reacciones), las Custom Wheels tienen opciones fijas que cada servidor configura una vez y puede usar ilimitadamente.

## 📋 Comandos Disponibles

### `/customwheels-settings`
Configura la ruleta personalizada de tu servidor.

**Requisitos:** Necesitas el permiso de "Manage Server" (Administrar Servidor).

**Proceso de configuración:**
1. Ejecuta `/customwheels-settings`
2. Click en "Set Number of Options" para establecer cuántas opciones quieres (mínimo 2, máximo 50)
3. Click en "Configure Options" para nombrar cada opción
   - Discord solo permite 5 campos de texto por vez
   - Si tienes más de 5 opciones, necesitarás hacer click múltiples veces
4. Click en "💾 Save Wheel" para guardar tu configuración
5. ¡Listo! Ya puedes usar tu ruleta

**Nota:** Si ya existe una ruleta configurada, se te preguntará si quieres reconfigurarla.

### `/customwheels-spin`
Gira la ruleta personalizada de tu servidor y obtén un resultado aleatorio.

- Cualquier miembro del servidor puede usar este comando
- Genera una imagen animada GIF mostrando la ruleta girando
- Muestra el resultado final en un embed elegante

### `/customwheels-view`
Muestra la configuración actual de la ruleta de tu servidor.

- Lista todas las opciones configuradas
- Muestra cuándo fue creada y actualizada
- Útil para recordar qué opciones tienes

## 💡 Ejemplos de Uso

### Ejemplo 1: Decidir qué jugar
```
Opciones:
1. Minecraft
2. Valorant
3. League of Legends
4. Among Us
5. Fall Guys
```

### Ejemplo 2: Elegir streaming
```
Opciones:
1. Horror game
2. Speedrun
3. Chill gameplay
4. Viewer games
5. Just chatting
```

### Ejemplo 3: Sorteo de premios
```
Opciones:
1. Discord Nitro
2. Steam gift card
3. Custom role
4. Server boost
5. Nothing (better luck next time!)
```

### Ejemplo 4: Retos del servidor
```
Opciones:
1. Post a meme
2. Share a fun fact
3. Tell a joke
4. Show your pet
5. Sing a song
```

## 🔧 Características Técnicas

- **Almacenamiento:** La configuración se guarda en PostgreSQL, permanente por servidor
- **Límites:** Mínimo 2 opciones, máximo 50 (por rendimiento)
- **Permisos:** Solo usuarios con "Manage Server" pueden configurar
- **Uso:** Todos los miembros pueden girar la ruleta
- **Visual:** Genera GIF animado con colores distintos para cada opción
- **Persistencia:** La configuración permanece hasta que la reconfigures

## ❓ Preguntas Frecuentes

**P: ¿Puedo tener múltiples ruletas en un servidor?**
R: No, cada servidor solo puede tener una ruleta personalizada configurada. Pero puedes reconfigurarla cuando quieras.

**P: ¿Las opciones son visibles para todos?**
R: Sí, usa `/customwheels-view` para ver todas las opciones configuradas.

**P: ¿Puedo editar solo una opción sin reconfigurar todo?**
R: No, actualmente necesitas reconfigurar toda la ruleta usando `/customwheels-settings`.

**P: ¿El resultado es verdaderamente aleatorio?**
R: Sí, usa el generador de números aleatorios de Python que es criptográficamente seguro.

**P: ¿Qué pasa si borro la base de datos?**
R: Perderás la configuración de la ruleta y tendrás que configurarla de nuevo.

## 🆚 Custom Wheels vs Wheels Normal

| Característica | Custom Wheels | Wheels Normal |
|---|---|---|
| Opciones | Personalizadas por servidor | Usuarios que reaccionan |
| Configuración | Una vez, persiste | Por cada uso |
| Quién puede usar | Todos | Solo después de reaccionar |
| Número de opciones | 2-50 fijas | Ilimitado (usuarios) |
| Uso | Decisiones repetibles | Sorteos únicos |

## 🎨 Personalización Visual

La ruleta generada incluye:
- ✅ Colores distintos para cada opción (usando espacio HSV)
- ✅ Animación de giro realista con desaceleración
- ✅ Nombres de opciones visibles en cada segmento
- ✅ Indicador rojo en la parte superior
- ✅ 3-5 vueltas completas antes de detenerse
- ✅ Formato GIF optimizado

## 🐛 Solución de Problemas

**Error: "This server doesn't have a custom wheel configured yet!"**
- Solución: Un administrador debe ejecutar `/customwheels-settings` primero.

**Error: "You need 'Manage Server' permission..."**
- Solución: Solo usuarios con permisos de administrador pueden configurar la ruleta.

**La imagen no se genera:**
- Causa: Falta la biblioteca Pillow
- Solución: El bot mostrará el resultado en texto sin la imagen animada.

**Las opciones no se guardan:**
- Verifica que completaste todos los campos antes de hacer click en "Save"
- Asegúrate de que la base de datos esté funcionando correctamente

## 📝 Notas de Desarrollo

- El código está en `oceanic_bot/games/custom_wheels.py`
- Usa asyncpg para la persistencia en PostgreSQL
- Genera GIF usando PIL/Pillow
- Compatible con discord.py v2.x
- Los modals tienen un timeout de 10 minutos
- Las vistas tienen un timeout de 10 minutos

---

¿Tienes preguntas o sugerencias? Contacta al desarrollador del bot.
