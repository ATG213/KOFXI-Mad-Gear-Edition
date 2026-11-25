r"""'Character palettes' tab of the KOF XI PS2 Toolkit (see gfx_palettes.py for the data side).

Everything is read from the input ISO set on tab 2; edited palettes are saved as <id>_<name>.PAL files (same format
as the arcade .PAL files) in the palettes folder, and tab 2 patches them into the new ISO.
"""
import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

import gfx_palettes as P

CELL = 17                 # swatch cell size in the tab (px)
ROW_LABEL_W = 150         # room right of the swatches for the names of the sprites that use a row
PREVIEW_H = 430           # body preview height (px), the sprite is scaled by an integer factor to fit
FX_BOX = (380, 330)       # effect preview box (px): scaled up by an integer factor or down to fit
BGS = {'Grey': (110, 110, 130), 'Black': (0, 0, 0), 'White': (255, 255, 255), 'Green': (40, 120, 40),
       'Stage blue': (60, 90, 150)}


class PaletteTab:
    def __init__(self, app, parent):
        self.app = app
        self.src = None              # gfx_palettes.Source of the current input ISO
        self.src_key = None
        self.loading = False
        self.edit = {}               # cid -> bytearray (working copy, mirrors the file in the palettes folder)
        self.cid = None
        self.color = 0
        self.hl = None               # (row, entry) highlighted in the previews while pointing at a swatch
        self.photos = [None, None, None, None]
        self.fx_ids = []             # descriptor numbers that can be browsed in the effect preview
        self.fx_pos = 0
        self.named = []              # [(sprite, name)] of the character (incl. the automatic LDM hit entry)
        self.build(parent)

    # ------------------------------------------------------------ layout
    def build(self, parent):
        f = ttk.Frame(parent, padding=8)
        f.pack(fill='both', expand=True)
        head = ttk.Frame(f)
        head.pack(fill='x')
        self.lbl_info = ttk.Label(head, text='', foreground='#444', wraplength=1100, justify='left')
        self.lbl_info.pack(side='left', fill='x', expand=True)
        ttk.Button(head, text='Open palettes folder', command=self.open_folder).pack(side='right', padx=(8, 0))
        self.var_folder = self.app.var_palettes          # set on the Folders tab
        ttk.Frame(f, height=6).pack(fill='x')

        body = ttk.Frame(f)
        body.pack(fill='both', expand=True)
        left = ttk.Frame(body)
        left.pack(side='left', fill='y')
        self.tree = ttk.Treeview(left, columns=('id', 'name', 'mod'), show='headings', selectmode='browse', height=24)
        for c, t, w in (('id', 'ID', 34), ('name', 'Character', 130), ('mod', 'Changed', 70)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor='w', stretch=False)
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='y')
        sb.pack(side='left', fill='y')
        self.tree.tag_configure('mod', background='#e4f4e4')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.on_char())

        mid = self.mid = ttk.Frame(body)
        mid.bind('<Configure>', self.on_resize)
        mid.pack(side='left', fill='both', expand=True, padx=10)
        top = ttk.Frame(mid)
        top.pack(fill='x')
        ttk.Label(top, text='Colour:').pack(side='left')
        self.var_color = tk.StringVar()
        self.cb_color = ttk.Combobox(top, textvariable=self.var_color, state='readonly', width=22)
        self.cb_color.pack(side='left', padx=6)
        self.cb_color.bind('<<ComboboxSelected>>', lambda e: self.on_color())
        ttk.Label(top, text='Background:').pack(side='left', padx=(12, 0))
        self.var_bg = tk.StringVar(value='Grey')
        cb = ttk.Combobox(top, textvariable=self.var_bg, state='readonly', width=11, values=list(BGS))
        cb.pack(side='left', padx=6)
        cb.bind('<<ComboboxSelected>>', lambda e: self.show_preview())
        pv = ttk.Frame(mid)
        pv.pack(fill='x', pady=6)
        self.pv = []
        for cap in ('Original', 'Yours'):
            col = ttk.Frame(pv)
            col.pack(side='left', fill='both', expand=True)
            ttk.Label(col, text=cap, foreground='#555').pack()
            lb = ttk.Label(col, anchor='center')
            lb.pack(fill='both', expand=True)
            self.pv.append(lb)
        fx = ttk.LabelFrame(mid, text='Effects (projectiles, flames, ...)')
        fx.pack(fill='x', pady=(2, 4))
        nav = ttk.Frame(fx)
        nav.pack(fill='x', padx=4, pady=2)
        ttk.Label(nav, text='Show:').pack(side='left')
        self.var_fx = tk.StringVar()
        self.cb_fx = ttk.Combobox(nav, textvariable=self.var_fx, state='readonly', width=26)
        self.cb_fx.pack(side='left', padx=(4, 10))
        self.cb_fx.bind('<<ComboboxSelected>>', lambda e: self.fx_pick())
        ttk.Button(nav, text='<', width=3, command=lambda: self.fx_step(-1)).pack(side='left')
        ttk.Button(nav, text='>', width=3, command=lambda: self.fx_step(1)).pack(side='left', padx=(2, 8))
        self.lbl_fx = ttk.Label(nav, text='', foreground='#444')
        self.lbl_fx.pack(side='left')
        self.var_allspr = tk.BooleanVar(value=False)
        ttk.Checkbutton(nav, text='all sprites', variable=self.var_allspr,
                        command=self.fx_reload).pack(side='left', padx=(10, 0))
        if self.app.cfg.get('curator'):             # maintainer only: edit the bundled list of named sprites
            cur = ttk.Frame(fx)
            cur.pack(fill='x', padx=4, pady=(0, 2))
            ttk.Label(cur, text='Curator:', foreground='#b86e00').pack(side='left')
            ttk.Button(cur, text='Add shown sprite to list...', command=self.fx_add).pack(side='left', padx=4)
            ttk.Button(cur, text='Remove from list', command=self.fx_remove).pack(side='left', padx=4)
        fpv = ttk.Frame(fx)
        fpv.pack(fill='x')
        for k in range(2):
            lb = ttk.Label(fpv, anchor='center')
            lb.pack(side='left', fill='both', expand=True)
            self.pv.append(lb)
        ttk.Label(mid, text='Body: first frame of the idle stance (row 0). Effects: pick a named sprite, or browse with '
                  '< > ("all sprites" also lists sprites in body colours). Point at a swatch to see which pixels it '
                  'colours. Rows used by several sprites change all of them (as in the game). Everything is rendered '
                  'from your ISO.',
                  foreground='#666', wraplength=560, justify='left').pack(anchor='w')

        right = ttk.Frame(body)
        right.pack(side='left', fill='y')
        ttk.Label(right, text='Palette of this colour (click a swatch to change it)', foreground='#444').pack(anchor='w')
        self.cv = tk.Canvas(right, width=40 + 16 * CELL + ROW_LABEL_W, height=4 + 16 * CELL, highlightthickness=0)
        self.cv.pack(anchor='w', pady=4)
        self.cv.bind('<Button-1>', self.on_click)
        self.cv.bind('<Motion>', self.on_motion)
        self.cv.bind('<Leave>', lambda e: self.set_hl(None))
        ttk.Label(right, text='Row 0 = body. Rows 1-15 = effects, flashes and special states; the names right of '
                  'a row are the listed sprites that use it. Entry 0 of every row is transparent.', foreground='#666',
                  wraplength=330 + ROW_LABEL_W, justify='left').pack(anchor='w')
        bt = ttk.LabelFrame(right, text='This colour')
        bt.pack(fill='x', pady=(8, 0))
        row = ttk.Frame(bt)
        row.pack(fill='x', pady=2)
        ttk.Button(row, text='Copy from colour:', command=self.copy_color).pack(side='left', padx=4)
        self.var_copy = tk.StringVar()
        self.cb_copy = ttk.Combobox(row, textvariable=self.var_copy, state='readonly', width=16)
        self.cb_copy.pack(side='left')
        row = ttk.Frame(bt)
        row.pack(fill='x', pady=2)
        ttk.Button(row, text='Import into this colour...', command=lambda: self.import_file(True)).pack(side='left',
                                                                                                     padx=4)
        ttk.Button(row, text='Reset colour', command=self.reset_color).pack(side='left', padx=4)
        row = ttk.Frame(bt)
        row.pack(fill='x', pady=2)
        ttk.Button(row, text='Export this colour as palette...', command=self.export_color).pack(side='left', padx=4)
        ttk.Label(row, text='.pal / .gpl / .act', foreground='#666').pack(side='left')
        bt = ttk.LabelFrame(right, text='Whole character (all 12 colours)')
        bt.pack(fill='x', pady=(8, 0))
        row = ttk.Frame(bt)
        row.pack(fill='x', pady=2)
        ttk.Button(row, text='Import palette / swatch PNG...', command=lambda: self.import_file(False)).pack(
            side='left', padx=4)
        ttk.Button(row, text='Reset character', command=self.reset_char).pack(side='left', padx=4)
        row = ttk.Frame(bt)
        row.pack(fill='x', pady=2)
        ttk.Button(row, text='Export game .PAL...', command=lambda: self.export('pal')).pack(side='left', padx=4)
        ttk.Button(row, text='Export swatch PNG...', command=lambda: self.export('png')).pack(side='left', padx=4)
        row = ttk.Frame(bt)
        row.pack(fill='x', pady=2)
        ttk.Button(row, text='Export preview PNG...', command=lambda: self.export('preview')).pack(side='left', padx=4)
        # the swatch column must never be cut off: give it its space first, the previews get the rest
        mid.pack_forget()
        right.pack_forget()
        right.pack(side='right', fill='y')
        mid.pack(side='left', fill='both', expand=True, padx=10)
        self.lbl_status = ttk.Label(f, text='', foreground='#1b7f2a')
        self.lbl_status.pack(anchor='w', pady=(6, 0))
        self.update_info()

    # ------------------------------------------------------------ data
    def iso_path(self):
        return self.app.iso_for_checks()

    def folder(self):
        return self.var_folder.get().strip()

    def default_folder(self):
        rd = self.app.ready_dir()
        import gfx_targets as T
        return os.path.join(rd, 'palettes') if rd else os.path.join(T.APP_DIR, 'palettes')

    def activate(self):
        """Called when the tab is shown: (re)load the ISO if it changed."""
        if not self.folder():
            self.var_folder.set(self.default_folder())
            self.save_cfg()
        iso = self.iso_path()
        key = (os.path.normcase(os.path.abspath(iso)), os.path.getmtime(iso)) if iso else None
        if key == self.src_key or self.loading:
            self.update_info()
            return
        self.src, self.src_key = None, key
        self.tree.delete(*self.tree.get_children())
        self.clear_view()
        if not iso:
            self.update_info()
            return
        self.loading = True
        self.update_info('Reading the palettes and sprites from %s ...' % os.path.basename(iso))
        self.app.bg(lambda: P.Source(iso), self.loaded)

    def loaded(self, src, err):
        self.loading = False
        if err:
            self.src = None
            self.update_info('Could not read the palettes from this ISO: %s' % err)
            return
        self.src = src
        self.reload_files()
        self.update_info()

    def reload_files(self):
        """Working copies = palette files of the folder (only those that fit this disc)."""
        self.edit = {}
        bad = []
        for cid, p in P.scan_folder(self.folder()).items():
            try:
                self.edit[cid] = bytearray(P.load_file(p, self.src.pals[cid]))
            except (SystemExit, OSError) as e:
                bad.append('%s (%s)' % (os.path.basename(p), e))
        self.fill_tree()
        if bad:
            self.status('Ignored: ' + '; '.join(bad), error=True)

    def fill_tree(self):
        sel = self.cid
        self.tree.delete(*self.tree.get_children())
        for cid in P.CHAR_IDS:
            mod = self.changed_colors(cid)
            self.tree.insert('', 'end', iid=str(cid), values=('%02X' % cid, P.CHAR_NAMES[cid],
                                                             ('%d colour%s' % (len(mod), 's' if len(mod) > 1 else ''))
                                                             if mod else ''), tags=('mod',) if mod else ())
        if sel is not None and self.tree.exists(str(sel)):
            self.tree.selection_set(str(sel))
            self.tree.see(str(sel))

    def changed_colors(self, cid):
        if cid not in self.edit or not self.src:
            return []
        a, b = self.src.pals[cid], self.edit[cid]
        return [c for c in range(P.n_colors(a)) if a[c * P.BLOCK:(c + 1) * P.BLOCK] != b[c * P.BLOCK:(c + 1) * P.BLOCK]]

    def cur(self):
        """Working palette of the selected character (the original if it was never changed)."""
        return self.edit.get(self.cid) or bytearray(self.src.pals[self.cid])

    def store(self, pal):
        """Save a changed palette to the folder (or remove the file again when it equals the original)."""
        cid = self.cid
        folder = self.folder()
        if not folder:
            return
        for c, p in P.scan_folder(folder).items():            # old names of the same character
            if c == cid and os.path.basename(p) != P.file_name(cid):
                os.remove(p)
        path = os.path.join(folder, P.file_name(cid))
        if bytes(pal) == self.src.pals[cid]:
            self.edit.pop(cid, None)
            if os.path.exists(path):
                os.remove(path)
            self.status('%s: back to the original colours (file removed)' % P.CHAR_NAMES[cid])
        else:
            os.makedirs(folder, exist_ok=True)
            self.edit[cid] = bytearray(pal)
            with open(path, 'wb') as fh:
                fh.write(bytes(pal))
            self.status('saved %s  -  tab 2 patches it into the new ISO' % path)
        self.fill_tree()
        self.show_all()

    # ------------------------------------------------------------ view
    def update_info(self, text=None):
        if text is None:
            if not self.iso_path():
                text = 'Choose the input ISO on tab 2 first: the palettes and the preview are read from it.'
            elif self.src:
                n = sum(1 for c in P.CHAR_IDS if self.changed_colors(c))
                text = ('%s disc: 47 characters x 12 colours. Pick a character and a colour, click a swatch to change '
                        'it. Changes are saved at once in the palettes folder (set on the Folders tab; %d character%s changed); tab 2 patches '
                        'them into the new ISO (FIGHT.BCC + FIGHTA.BCC).' % (self.src.variant or '?', n,
                                                                             '' if n == 1 else 's'))
                if self.src.mismatch:
                    text += ' Note: FIGHT.BCC and FIGHTA.BCC differ on this disc for %s.' % ', '.join(
                        P.CHAR_NAMES[c] for c in self.src.mismatch)
            else:
                text = ''
        self.lbl_info.config(text=text)

    def status(self, text, error=False):
        self.lbl_status.config(text=text, foreground='#b00020' if error else '#1b7f2a')

    def clear_view(self):
        self.cid = None
        self.cv.delete('all')
        for i, lb in enumerate(self.pv):
            self.photos[i] = None
            lb.config(image='', text='')

    def on_char(self):
        s = self.tree.selection()
        if not s or not self.src:
            return
        self.cid = int(s[0])
        n = P.n_colors(self.src.pals[self.cid])
        labels = ['%d  %s' % (i + 1, P.COLOR_LABELS[i]) for i in range(n)]
        self.cb_color.config(values=labels)
        self.cb_copy.config(values=labels)
        self.color = min(self.color, n - 1)
        self.var_color.set(labels[self.color])
        self.var_copy.set('')
        self.hl = None
        self.fx_reload(reset=True)

    def on_color(self):
        try:
            self.color = int(self.var_color.get().split()[0]) - 1
        except (ValueError, IndexError):
            self.color = 0
        self.show_all()

    def show_all(self):
        self.draw_swatches()
        self.show_preview()

    def draw_swatches(self):
        cv = self.cv
        cv.delete('all')
        if self.cid is None:
            return
        pal = self.cur()
        orig = self.src.pals[self.cid]
        for sub in range(P.subs_in_color(pal, self.color)):
            y = 2 + sub * CELL
            cv.create_text(16, y + CELL // 2, text=str(sub), fill='#1b5fbf' if sub == 0 else '#555',
                           font=('Segoe UI', 8, 'bold' if sub == 0 else 'normal'))
            for i in range(16):
                x = 34 + i * CELL
                if i == 0:
                    cv.create_rectangle(x, y, x + CELL - 2, y + CELL - 2, outline='#bbb', fill='')
                    cv.create_line(x, y + CELL - 2, x + CELL - 2, y, fill='#bbb')
                    continue
                w = P.get_word(pal, self.color, sub, i)
                ch = w != P.get_word(orig, self.color, sub, i)
                cv.create_rectangle(x, y, x + CELL - 2, y + CELL - 2, fill='#%02x%02x%02x' % P.word_to_rgb(w),
                                    outline='#d00000' if ch else '#888', width=2 if ch else 1)
            names = ['body'] if sub == 0 else []
            names += [n for i, n in self.named if P.sprite_row(self.src.ref_sprite(self.cid, i)[0]) == sub]
            if names:
                txt = ', '.join(dict.fromkeys(names))
                if len(txt) > 24:
                    txt = txt[:23] + '...'
                cv.create_text(38 + 16 * CELL, y + CELL // 2, text=txt, anchor='w', fill='#444',
                               font=('Segoe UI', 8))

    def cell_at(self, ev):
        sub, i = (ev.y - 2) // CELL, (ev.x - 34) // CELL
        if self.cid is None or ev.x < 34 or not (0 <= i < 16):
            return None
        if not (0 <= sub < P.subs_in_color(self.cur(), self.color)):
            return None
        return sub, i

    def on_motion(self, ev):
        c = self.cell_at(ev)
        self.set_hl(c if c and c[1] > 0 else None)

    def set_hl(self, cell):
        if cell != self.hl:
            self.hl = cell
            self.show_preview()

    # ------------------------------------------------------------ effect preview
    def fx_reload(self, reset=False):
        """Rebuild the list of browsable sprites; start at the first named sprite of the character."""
        if self.cid is None or not self.src:
            return
        cur = None if reset or not self.fx_ids else self.fx_ids[self.fx_pos]
        self.named = self.src.named(self.cid)
        ids = set(self.src.effect_ids(self.cid, bool(self.var_allspr.get())))
        ids |= {i for i, n in self.named}          # named sprites in body colours stay reachable
        self.fx_ids = sorted(ids)
        if cur is None or cur not in self.fx_ids:
            cur = self.named[0][0] if self.named else self.src.default_effect(self.cid)
        self.fx_pos = self.fx_ids.index(cur) if cur in self.fx_ids else 0
        self.cb_fx.config(values=[n for i, n in self.named] or ['(none listed)'])
        self.show_all()

    def fx_pick(self):
        name = self.var_fx.get()
        for i, n in self.named:
            if n == name and i in self.fx_ids:
                self.fx_pos = self.fx_ids.index(i)
                self.show_preview()
                return

    def fx_step(self, d):
        if self.fx_ids:
            self.fx_pos = (self.fx_pos + d) % len(self.fx_ids)
            self.show_preview()

    def fx_current(self):
        """(descriptor number, descriptor, tile data) of the shown effect sprite, or None."""
        if self.cid is None or not self.fx_ids:
            return None
        i = self.fx_ids[self.fx_pos]
        sp = self.src.ref_sprite(self.cid, i)
        return (i, sp[0], sp[1]) if sp else None

    def fx_add(self):
        cur = self.fx_current()
        if not cur:
            return
        name = simpledialog.askstring('Add to list', 'Name for sprite %d of %s (e.g. Fireball):'
                                      % (cur[0], P.CHAR_NAMES[self.cid]), parent=self.cv)
        if not name or not name.strip():
            return
        items = [(i, n) for i, n in self.src.named(self.cid, with_ldm=False) if i != cur[0]] + [(cur[0], name.strip())]
        self.fx_save(items)

    def fx_remove(self):
        cur = self.fx_current()
        if not cur:
            return
        items = self.src.named(self.cid, with_ldm=False)
        if cur[0] not in [i for i, n in items]:
            self.status('sprite %d is not in the list (the LDM hit entry is automatic)' % cur[0], error=True)
            return
        self.fx_save([(i, n) for i, n in items if i != cur[0]])

    def fx_save(self, items):
        try:
            p = P.save_fx(self.cid, items)
        except OSError as e:
            self.status('could not save the list: %s' % e, error=True)
            return
        self.status('%s: list saved in %s (%d named sprites)' % (P.CHAR_NAMES[self.cid], p, len(items)))
        self.fx_reload()

    def on_click(self, ev):
        c = self.cell_at(ev)
        if not c or c[1] == 0:
            return
        sub, i = c
        pal = self.cur()
        old = P.word_to_rgb(P.get_word(pal, self.color, sub, i))
        res = colorchooser.askcolor(color='#%02x%02x%02x' % old,
                                    title='%s, colour %d, row %d, entry %d' % (P.CHAR_NAMES[self.cid], self.color + 1,
                                                                               sub, i))
        if not res or not res[0]:
            return
        pal = bytearray(pal)
        if P.set_rgb(pal, self.color, sub, i, res[0]):
            self.store(pal)

    def box_w(self):
        """Width one of the two previews (Original / Yours) may take: half of the middle column."""
        w = self.mid.winfo_width()
        return max(150, w // 2 - 16) if w > 1 else 300

    def on_resize(self, ev=None):
        """Re-render the previews when the window size changes (debounced)."""
        if getattr(self, '_rs', None):
            self.mid.after_cancel(self._rs)
        w = self.mid.winfo_width()
        if w != getattr(self, '_last_w', None):
            self._last_w = w
            self._rs = self.mid.after(120, self.show_preview)

    def render(self, pal, sprite, row, box):
        hl = self.hl[1] if self.hl and self.hl[0] == row else None
        im = P.render_idle(sprite, pal, self.color, row, hl)
        bb = im.getbbox()
        if bb:
            im = im.crop(bb)
        if im.width <= box[0] and im.height <= box[1]:
            s = max(1, min(4, box[0] // max(1, im.width), box[1] // max(1, im.height)))
            im = im.resize((im.width * s, im.height * s), Image.NEAREST)
        else:
            im.thumbnail(box, Image.LANCZOS)
        bg = Image.new('RGBA', im.size, BGS[self.var_bg.get()] + (255,))
        bg.alpha_composite(im)
        return bg

    def show_preview(self):
        if self.cid is None or not self.src:
            return
        sp = self.src.sprite(self.cid)
        fx = self.fx_current()
        if fx:
            i, d, pix = fx
            self.lbl_fx.config(text=('console sprite %d, row %d' % (i - P.PL_REF, P.sprite_row(d))) if i >= P.PL_REF
                               else 'sprite %d, row %d' % (i, P.sprite_row(d)))
            self.var_fx.set(next((n for j, n in self.named if j == i), '-'))
        else:
            self.var_fx.set('')
            self.lbl_fx.config(text='no effect sprites (tick "all sprites")')
        for k, pal in enumerate((self.src.pals[self.cid], self.cur())):
            for slot, what in ((k, 'body'), (k + 2, 'fx')):
                if what == 'body':
                    im = self.render(pal, sp, 0, (self.box_w(), PREVIEW_H)) if sp else None
                else:
                    im = self.render(pal, (fx[1], fx[2]), P.sprite_row(fx[1]), (min(FX_BOX[0], self.box_w()), FX_BOX[1])) if fx else None
                if im is None:
                    self.photos[slot] = None
                    self.pv[slot].config(image='', text='(no sprite found)' if what == 'body' else '')
                else:
                    self.photos[slot] = ImageTk.PhotoImage(im.convert('RGB'))
                    self.pv[slot].config(image=self.photos[slot], text='')

    # ------------------------------------------------------------ actions
    def need_char(self):
        if self.cid is None or not self.src:
            messagebox.showinfo('Character palettes', 'Pick a character first (and set the input ISO on tab 2).')
            return False
        if not self.folder():
            self.choose_folder()
        return bool(self.folder())

    def copy_color(self):
        if not self.need_char():
            return
        try:
            src_c = int(self.var_copy.get().split()[0]) - 1
        except (ValueError, IndexError):
            messagebox.showinfo('Copy colour', 'Choose the colour to copy from in the box next to the button.')
            return
        pal = bytearray(self.cur())
        a, b = src_c * P.BLOCK, self.color * P.BLOCK
        n = min(P.BLOCK, len(pal) - a, len(pal) - b)
        pal[b:b + n] = pal[a:a + n]
        self.store(pal)

    def reset_color(self):
        if not self.need_char():
            return
        pal = bytearray(self.cur())
        a = self.color * P.BLOCK
        pal[a:a + P.BLOCK] = self.src.pals[self.cid][a:a + P.BLOCK]
        self.store(pal)

    def reset_char(self):
        if not self.need_char():
            return
        if self.cid in self.edit and not messagebox.askyesno(
                'Reset', 'Reset all 12 colours of %s to the original?' % P.CHAR_NAMES[self.cid]):
            return
        self.store(bytearray(self.src.pals[self.cid]))

    def import_file(self, only_color):
        if not self.need_char():
            return
        p = filedialog.askopenfilename(title='Palette for %s' % P.CHAR_NAMES[self.cid],
                                       initialdir=self.app.cfg.get('last_dir') or None,
                                       filetypes=[('Palette files and swatch PNG', '*.pal *.gpl *.act *.png'),
                                                  ('All files', '*.*')])
        if not p:
            return
        self.app.cfg['last_dir'] = os.path.dirname(p)
        base = bytes(self.cur())
        try:
            data = P.load_file(p, base, self.color if only_color else None)
        except (SystemExit, ValueError, OSError) as e:
            messagebox.showerror('Import', str(e))
            return
        if only_color:
            pal = bytearray(base)
            a = self.color * P.BLOCK
            pal[a:a + P.BLOCK] = data[a:a + P.BLOCK]
        else:
            pal = bytearray(data)
        self.store(pal)

    def export_color(self):
        """The selected colour slot (16 rows x 16 entries = 256 colours) as a common palette file."""
        if self.cid is None or not self.src:
            messagebox.showinfo('Export', 'Pick a character first.')
            return
        stem = '%s_colour%d' % (P.file_name(self.cid)[:-4], self.color + 1)
        p = filedialog.asksaveasfilename(title='Export colour %d as palette' % (self.color + 1),
                                         initialdir=self.app.cfg.get('last_dir') or None, initialfile=stem + '.pal',
                                         defaultextension='.pal',
                                         filetypes=[(n, '*' + e) for n, e in P.PAL_FORMATS])
        if not p:
            return
        self.app.cfg['last_dir'] = os.path.dirname(p)
        if os.path.splitext(p)[1].lower() not in [e for n, e in P.PAL_FORMATS]:
            p += '.pal'
        P.write_palette(p, P.color_rgbs(self.cur(), self.color),
                        '%s colour %d' % (P.CHAR_NAMES[self.cid], self.color + 1))
        self.status('exported %s (256 colours: 16 rows x 16 entries; import it again with "Import into this colour")'
                    % p)

    def export(self, what):
        if self.cid is None or not self.src:
            messagebox.showinfo('Export', 'Pick a character first.')
            return
        name = P.file_name(self.cid)
        ext = {'pal': '.PAL', 'png': '_swatch.png', 'preview': '_colour%d.png' % (self.color + 1)}[what]
        fx = self.fx_current() if what == 'preview' else None
        p = filedialog.asksaveasfilename(title='Export', initialdir=self.app.cfg.get('last_dir') or None,
                                         initialfile=name[:-4] + ext,
                                         defaultextension='.png' if what != 'pal' else '.PAL',
                                         filetypes=[('PNG', '*.png')] if what != 'pal' else [('Palette', '*.PAL')])
        if not p:
            return
        self.app.cfg['last_dir'] = os.path.dirname(p)
        pal = bytes(self.cur())
        if what == 'pal':
            with open(p, 'wb') as fh:
                fh.write(pal)
        elif what == 'png':
            P.swatch_image(pal).save(p)
        else:
            sp = self.src.sprite(self.cid)
            if not sp:
                messagebox.showerror('Export', 'No sprite found for this character.')
                return
            body = P.render_idle(sp, pal, self.color)
            if fx:                       # body and the shown effect side by side
                eff = P.render_idle((fx[1], fx[2]), pal, self.color, P.sprite_row(fx[1]))
                bb = eff.getbbox()
                eff = eff.crop(bb) if bb else eff
                out = Image.new('RGBA', (body.width + 8 + eff.width, max(body.height, eff.height)), (0, 0, 0, 0))
                out.alpha_composite(body, (0, out.height - body.height))
                out.alpha_composite(eff, (body.width + 8, out.height - eff.height))
                body = out
            body.save(p)
        self.status('exported %s' % p)

    def choose_folder(self):
        p = filedialog.askdirectory(title='Folder for your character palettes (.PAL files)',
                                    initialdir=self.folder() or self.app.cfg.get('last_dir') or None)
        if p:
            self.var_folder.set(os.path.normpath(p))
            self.save_cfg()
            self.folder_changed()

    def folder_changed(self):
        """The palettes folder was changed (here or on the Folders tab): reload the files."""
        if self.src:
            self.reload_files()
            if self.cid is not None:
                self.show_all()
            self.update_info()

    def open_folder(self):
        f = self.folder()
        if f:
            os.makedirs(f, exist_ok=True)
            os.startfile(f)

    def save_cfg(self):
        self.app.cfg['palettes'] = self.folder()
        self.app.pull_settings()
