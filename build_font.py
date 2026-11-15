from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
from unicodedata import category, east_asian_width

from fontTools import subset
from fontTools.misc.roundTools import otRound
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.ttLib.tables.ttProgram import Program

FAMILY = 'Genshin Terminal Mono'
RANGES = (
    (0x0020, 0x024F), (0x0300, 0x036F), (0x1E00, 0x1EFF),
    (0x2000, 0x26FF),
    (0x2E80, 0x31FF), (0x3400, 0x9FFF), (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF), (0x20000, 0x323AF),
)
CELL = 640
MARGIN = 26


def glyph_class(codepoint):
    char = chr(codepoint)
    if category(char) in {'Mn', 'Me', 'Cf'}:
        return 0, 'mark'
    if 0x2500 <= codepoint <= 0x259F:
        return CELL, 'box'
    if east_asian_width(char) in {'W', 'F'}:
        placement = 'punctuation' if category(char).startswith('P') else 'wide'
        return 2 * CELL, placement
    return CELL, 'narrow'


def fit_outline(original, glyf, advance, placement, old_advance, old_lsb):
    coords, endpoints, flags = original.getCoordinates(glyf)
    outline = Glyph()
    outline.numberOfContours = len(endpoints)
    if not endpoints:
        return outline, 0

    left = min(x for x, _ in coords)
    right = max(x for x, _ in coords)
    span = right - left
    if placement == 'mark':
        factor = 1.0
        shift = old_lsb - left
    elif placement == 'box' and old_advance:
        factor = advance / old_advance
        shift = (old_lsb - left) * factor
    else:
        max_scale = 1.12 if placement == 'wide' else 1.0
        factor = min(max_scale, (advance - 2 * MARGIN) / span) if span else 1.0
        new_left = (advance - span * factor) / 2
        if placement == 'punctuation':
            relative_left = old_lsb + (advance - old_advance) / 2 if old_advance >= CELL else old_lsb
            new_left = min(max(MARGIN, relative_left), advance - MARGIN - span * factor)
        shift = new_left - left * factor

    outline.coordinates = GlyphCoordinates([(otRound(x * factor + shift), y) for x, y in coords])
    outline.endPtsOfContours = list(endpoints)
    outline.flags = flags
    outline.program = Program()
    outline.program.fromBytecode(b'')
    return outline, min(x for x, _ in outline.coordinates)


def build(source, output):
    font = TTFont(source, recalcTimestamp=False)
    available = font.getBestCmap()
    codepoints = {cp for cp in available if any(lo <= cp <= hi for lo, hi in RANGES)}
    options = subset.Options()
    options.hinting = False
    options.layout_features = []
    options.name_IDs = ['*']
    options.glyph_names = True
    selection = subset.Subsetter(options=options)
    selection.populate(unicodes=codepoints)
    selection.subset(font)

    glyph_groups = defaultdict(lambda: defaultdict(list))
    for cp, glyph_name in font.getBestCmap().items():
        glyph_groups[glyph_name][glyph_class(cp)].append(cp)

    glyf = font['glyf']
    metrics = font['hmtx'].metrics
    original_order = font.getGlyphOrder()
    glyph_order = list(original_order)
    replacement = {}
    outlines = {}
    for glyph_name in original_order:
        if glyph_name not in glyph_groups and glyph_name != '.notdef':
            continue
        variants = glyph_groups[glyph_name] or {(CELL, 'narrow'): []}
        for index, ((advance, placement), characters) in enumerate(variants.items()):
            name = glyph_name
            if index:
                name = f'{glyph_name}.terminal{index}'
                glyph_order.append(name)
            outline, bearing = fit_outline(glyf[glyph_name], glyf, advance, placement, *metrics[glyph_name])
            outlines[name] = (outline, advance, bearing)
            replacement.update({cp: name for cp in characters})

    for name, (outline, advance, bearing) in outlines.items():
        glyf[name] = outline
        metrics[name] = (advance, bearing)
    font.setGlyphOrder(glyph_order)
    for cmap in font['cmap'].tables:
        if cmap.isUnicode() and hasattr(cmap, 'cmap'):
            cmap.cmap.update({cp: replacement[cp] for cp in cmap.cmap if cp in replacement})
    for tag in ('vhea', 'vmtx', 'GDEF', 'GPOS', 'GSUB', 'kern'):
        if tag in font:
            del font[tag]

    # Remove old composite-only glyphs after their contours have been copied.
    selection = subset.Subsetter(options=options)
    selection.populate(unicodes=codepoints)
    selection.subset(font)
    names = font['name']
    new_names = {
        1: FAMILY, 2: 'Regular', 3: 'GenshinTerminalMono-Regular-1.0',
        4: FAMILY, 5: 'Version 1.0', 6: 'GenshinTerminalMono-Regular',
        16: FAMILY, 17: 'Regular', 21: FAMILY, 22: 'Regular',
    }
    names.names = [record for record in names.names if record.nameID not in new_names]
    for name_id, text in new_names.items():
        names.setName(text, name_id, 3, 1, 0x409)
    font['post'].isFixedPitch = 1
    font.save(output)
    print(output)


if __name__ == '__main__':
    parser = ArgumentParser(description='Build the Genshin Terminal Mono font')
    parser.add_argument('source', type=Path, help='Path to the upstream HYWenHei Extended.ttf file')
    parser.add_argument('--output', type=Path, default=Path('GenshinTerminalMono-Regular.ttf'))
    args = parser.parse_args()
    build(args.source, args.output)
