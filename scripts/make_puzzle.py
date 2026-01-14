#!/usr/bin/env python3
"""
Divide una imagen en filas x columnas, mezcla las piezas y genera
una imagen final con las piezas mezcladas a la izquierda y la imagen
completa a la derecha.
"""
import argparse
import random
from PIL import Image, ImageDraw


def make_puzzle(input_path, out_path, rows=4, cols=4, padding=10, border=2, bg_color=(40,40,40)):
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size

    tile_w = w // cols
    tile_h = h // rows

    # Recortar piezas
    tiles = []
    for r in range(rows):
        for c in range(cols):
            left = c * tile_w
            upper = r * tile_h
            # Si la imagen no se divide exactamente, aseguramos que la última columna/filad cubra el resto
            right = left + tile_w if c < cols - 1 else w
            lower = upper + tile_h if r < rows - 1 else h
            tile = img.crop((left, upper, right, lower))
            tiles.append(tile)

    # Mezclar
    shuffled = tiles[:]
    random.shuffle(shuffled)

    # Preparar canvas combinado: izquierda las piezas, derecha la imagen completa
    gap = padding
    left_width = max(tile_w * cols, w)
    right_width = w
    total_width = left_width + gap + right_width
    total_height = h

    out = Image.new("RGBA", (total_width, total_height), bg_color)

    # Dibujar piezas mezcladas en la izquierda en una grilla rows x cols
    idx = 0
    for r in range(rows):
        for c in range(cols):
            tile = shuffled[idx]
            # Calcular tamaño del tile actual (puede variar en última fila/col)
            tw, th = tile.size
            x = c * tile_w
            y = r * tile_h
            out.paste(tile, (x, y), tile)
            # Dibujar borde alrededor de cada pieza
            if border > 0:
                draw = ImageDraw.Draw(out)
                draw.rectangle([x, y, x + tw - 1, y + th - 1], outline=(0,0,0,200), width=border)
            idx += 1

    # Pegar la imagen original a la derecha
    out.paste(img, (left_width + gap, 0), img)

    # Guardar como PNG
    out.convert("RGB").save(out_path, "PNG")
    print(f"Puzzle guardado en: {out_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Genera una imagen tipo puzzle: piezas a la izquierda, original a la derecha.")
    parser.add_argument('input', help='Ruta de la imagen de entrada')
    parser.add_argument('--out', '-o', default='output_puzzle.png', help='Ruta de salida (PNG)')
    parser.add_argument('--rows', type=int, default=4, help='Número de filas')
    parser.add_argument('--cols', type=int, default=4, help='Número de columnas')
    parser.add_argument('--padding', type=int, default=10, help='Espacio entre secciones')
    parser.add_argument('--border', type=int, default=2, help='Grosor de borde en piezas')

    args = parser.parse_args()
    make_puzzle(args.input, args.out, rows=args.rows, cols=args.cols, padding=args.padding, border=args.border)
