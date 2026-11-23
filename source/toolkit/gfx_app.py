r"""KOF XI PS2 graphics replacer (JP and US disc): Windows GUI (tkinter).

Tab 1  Convert: pick a graphic, pick your PNG, get checks and a preview, convert it into the "ready" folder.
Tab 2  Patch:   pick the input ISO and a folder, every file in it that is a known graphic (e116.png, LOGO04.png,
                attract.png, ...) is written into a NEW copy of the ISO.  The input ISO is never modified.
Settings: all folders are chosen in the app and saved (gfx_tool_config.json next to this file).

Needs Python 3 with Pillow and numpy.  Start with gfx_tool.bat or:  pyw -3 gfx_app.py
"""
import json
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np                      # noqa: E402
from PIL import Image, ImageTk          # noqa: E402

import gfx_convert as C                 # noqa: E402
import gfx_hacks as H                   # noqa: E402
import kofxi_gfx as G                   # noqa: E402
import gfx_menu as M                    # noqa: E402
import gfx_targets as T                 # noqa: E402

CONFIG_NAMES = ([os.environ['KOFXI_GFX_CONFIG']] if os.environ.get('KOFXI_GFX_CONFIG') else []) + [
    os.path.join(T.APP_DIR, 'gfx_tool_config.json'), os.path.join(os.path.expanduser('~'), '.kofxi_gfx_tool.json')]
DEFAULTS = {'originals': '', 'replacements': '', 'ready': '', 'iso_in': '', 'iso_out': '', 'last_dir': '',
            'fit': False, 'scale': 1.0, 'dx': 0, 'dy': 0, 'auto_fix': False, 'hacks': [], 'ui_color': '',
            'hide_anim': False, 'black_bg': False, 'frame_color': '', 'margin_color': '', 'clock_rot': 90, 'font_orange': '', 'font_teal': ''}
COLORS = {'error': '#b00020', 'warn': '#b86e00', 'ok': '#1b7f2a', 'info': '#222222'}
PREVIEW_BOX = (300, 250)
ROT_LABELS = {0: 'none', 90: '90 deg clockwise', 180: '180 deg', 270: '90 deg counter-clockwise'}


def load_config():
    for p in CONFIG_NAMES:
        try:
            with open(p, encoding='utf-8') as f:
                return {**DEFAULTS, **json.load(f)}
        except (OSError, ValueError):
            continue
    return dict(DEFAULTS)


def active_config_path():
    """The settings file that is really used: the first existing one, else the first whose folder is writable."""
    for p in CONFIG_NAMES:
        if os.path.isfile(p):
            return p
    for p in CONFIG_NAMES:
        if os.access(os.path.dirname(p) or '.', os.W_OK):
            return p
    return CONFIG_NAMES[0]


def save_config(cfg):
    for p in CONFIG_NAMES:
        try:
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=1)
            return
        except OSError:
            continue


def checker(size, a=10):
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    v = np.where(((xx // a) + (yy // a)) % 2 == 0, 200, 150).astype(np.uint8)
    return Image.fromarray(np.stack([v, v, v, np.full_like(v, 255)], -1), 'RGBA')


def render_preview(im, bg_name):
    """RGBA image -> PhotoImage scaled into PREVIEW_BOX on the chosen background."""
    s = min(PREVIEW_BOX[0] / im.width, PREVIEW_BOX[1] / im.height, 3.0)
    nw, nh = max(1, int(im.width * s)), max(1, int(im.height * s))
    im = im.resize((nw, nh), Image.NEAREST if s > 1 else Image.LANCZOS)
    if bg_name == 'Checkerboard':
        bg = checker(im.size)
    else:
        col = {'Black': (0, 0, 0), 'White': (255, 255, 255), 'Green': (40, 120, 40),
               'Orange': (210, 120, 30)}[bg_name]
        bg = Image.new('RGBA', im.size, col + (255,))
    bg.alpha_composite(im)
    return ImageTk.PhotoImage(bg.convert('RGB'))


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.q = queue.Queue()
        self.targets = T.all_targets()
        self.orig_index = {}
        self.repl_index = {}
        self.result = None
        self.check_id = 0
        self.photo = [None, None]
        self.patch_rows = {}
        self.busy = False
        root.title('KOF XI PS2 Toolkit  v%s' % T.TOOL_VERSION)
        root.geometry('1240x760')
        root.minsize(1120, 640)
        root.protocol('WM_DELETE_WINDOW', self.close)
        nb = self.nb = ttk.Notebook(root)
        nb.pack(fill='both', expand=True, padx=6, pady=6)
        self.untick = set()          # keys the user unticked by hand (kept across rescans)
        self.scan_sig = None
        self.auto_retry = False
        self.retry_patch = False
        self.tab_conv, self.tab_patch, self.tab_set = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.tab_conv, text='  1  Convert a graphic  ')
        nb.add(self.tab_patch, text='  2  Patch into ISO  ')
        nb.add(self.tab_set, text='  Graphics folders (optional)  ')
        self.build_settings()
        self.build_convert()
        self.build_patch()
        self.default_out()
        self.refresh_indexes()
        self.fill_targets()
        self.poll()
        self.fit_window()
        nb.select(self.tab_patch)
        nb.bind('<<NotebookTabChanged>>', self.on_tab)

    def fit_window(self):
        """Open large enough that every tab (incl. the Patch button of tab 2) is fully visible; never taller than the
        screen.  The log box at the bottom of tab 2 is the part that shrinks."""
        root = self.nb.winfo_toplevel()
        root.update_idletasks()
        need_h = max(f.winfo_reqheight() for f in (self.tab_conv, self.tab_patch, self.tab_set)) + 70
        need_w = max(f.winfo_reqwidth() for f in (self.tab_conv, self.tab_patch, self.tab_set)) + 30
        w = min(max(1240, need_w), root.winfo_screenwidth() - 40)
        h = min(max(760, need_h), root.winfo_screenheight() - 90)
        root.geometry('%dx%d' % (w, h))
        root.minsize(min(1120, w), min(640, h))

    # ------------------------------------------------------------ plumbing
    def bg(self, fn, done):
        def work():
            try:
                res, err = fn(), None
            except BaseException as e:      # SystemExit carries our own error texts
                res, err = None, e
            self.q.put(('call', done, res, err))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == 'call':
                    item[1](item[2], item[3])
                elif item[0] == 'log':
                    self.log_add(item[1])
                elif item[0] == 'progress':
                    self.progress['value'] = 100.0 * item[1] / max(1, item[2])
        except queue.Empty:
            pass
        self.root.after(60, self.poll)

    def close(self):
        self.pull_settings()
        save_config(self.cfg)
        self.root.destroy()

    def folder_row(self, parent, row, label, key, hint='', save=False, file_types=None, is_file=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
        var = tk.StringVar(value=self.cfg.get(key, ''))
        setattr(self, 'var_' + key, var)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky='ew', pady=4)

        def browse():
            cur = var.get()
            init = cur if os.path.isdir(cur) else (os.path.dirname(cur) if cur else self.cfg.get('last_dir') or None)
            if is_file and save:
                p = filedialog.asksaveasfilename(initialdir=init, title=label, defaultextension='.iso',
                                                 filetypes=file_types or [('ISO', '*.iso')])
            elif is_file:
                p = filedialog.askopenfilename(initialdir=init, title=label, filetypes=file_types or [('ISO', '*.iso')])
            else:
                p = filedialog.askdirectory(initialdir=init, title=label, mustexist=True)
            if p:
                var.set(os.path.normpath(p))
                self.cfg['last_dir'] = os.path.dirname(os.path.normpath(p))
                self.pull_settings()
        ttk.Button(parent, text='Browse...', command=browse).grid(row=row, column=2, padx=(8, 0), pady=4)
        if hint:
            ttk.Label(parent, text=hint, foreground='#666').grid(row=row + 1, column=1, sticky='w')
        return var

    def pull_settings(self):
        for k in ('originals', 'replacements', 'ready', 'iso_in', 'iso_out'):
            v = getattr(self, 'var_' + k, None)
            if v is not None:
                self.cfg[k] = v.get().strip()
        if getattr(self, 'hack_vars', None):
            self.cfg['hacks'] = [k for k, v in self.hack_vars.items() if v.get()]
        if getattr(self, 'var_ui_color', None) is not None:
            self.cfg['ui_color'] = self.var_ui_color.get().strip()
            self.cfg['hide_anim'] = bool(self.var_hide_anim.get())
            self.cfg['black_bg'] = bool(self.var_black_bg.get())
            self.cfg['frame_color'] = self.var_frame_color.get().strip()
            self.cfg['margin_color'] = self.var_margin_color.get().strip()
            self.cfg['font_orange'] = self.var_font_orange.get().strip()
            self.cfg['font_teal'] = self.var_font_teal.get().strip()
        save_config(self.cfg)

    # ------------------------------------------------------------ settings tab
    def build_settings(self):
        f = ttk.Frame(self.tab_set, padding=16)
        f.pack(fill='both', expand=True)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text='Optional folders for replacing graphics (saved automatically)',
                  font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(f, text='All of this is optional. You only need these folders if you want to replace game graphics '
                  '(logos, title screen, ...). Game hacks and menu colours work with all three left empty.',
                  foreground='#444', wraplength=900, justify='left').grid(row=1, column=0, columnspan=3, sticky='w',
                                                                         pady=(2, 10))
        self.folder_row(f, 2, 'Original graphics (optional):', 'originals',
                        'Folder with the original game graphics (e116.png, LOGO04.png, ...). '
                        'Only used for the "Original" preview on tab 1.')
        self.folder_row(f, 4, 'Your replacement files (optional):', 'replacements',
                        'Folder with your own PNGs. A file is picked up if its name starts with the graphic key, '
                        'e.g. e116_new.png.')
        self.folder_row(f, 6, 'Ready folder (optional):', 'ready',
                        'Where converted graphics are saved (e116.png, LOGO04.png, ...). '
                        'Empty = you are asked on the first convert.')
        ttk.Button(f, text='Apply and rescan', command=self.apply_settings).grid(row=8, column=1, sticky='w', pady=16)
        info = ('Graphic names: LOGO00-LOGO05 (start-up screens), NEW00-NEW10 (unlock screens), e001-e122 (title and '
                'intro graphics, e116 = title logo), attract (attract-mode logo), clock (main menu clock).\n\n'
                'Toolkit version %s. Your settings are saved in: %s' % (T.TOOL_VERSION, active_config_path()))
        ttk.Label(f, text=info, foreground='#444', wraplength=900, justify='left').grid(row=9, column=0,
                                                                                         columnspan=3, sticky='w')

    def apply_settings(self):
        self.pull_settings()
        self.refresh_indexes()
        self.fill_targets()

    # ------------------------------------------------------------ indexes
    def refresh_indexes(self):
        self.orig_index, self.repl_index = {}, {}
        rep = self.cfg['replacements']
        if self.cfg['originals'] and os.path.isdir(self.cfg['originals']):
            skip = os.path.normcase(os.path.abspath(rep)) if rep else None
            best = {}
            for d, dirs, files in os.walk(self.cfg['originals']):
                if skip and os.path.normcase(os.path.abspath(d)).startswith(skip):
                    dirs[:] = []
                    continue
                if os.path.basename(d).lower() in ('replacements', 'ready'):
                    dirs[:] = []
                    continue
                for fn in files:
                    if not fn.lower().endswith('.png'):
                        continue
                    k = T.match_name(fn)
                    if not k:
                        continue
                    stem = os.path.splitext(fn)[0]
                    score = 0 if stem.lower() == k.lower() else (1 if 'original' in stem.lower() else 2)
                    if k not in best or score < best[k][0]:
                        best[k] = (score, os.path.join(d, fn))
            self.orig_index = {k: v[1] for k, v in best.items()}
        if rep and os.path.isdir(rep):
            for fn in os.listdir(rep):
                p = os.path.join(rep, fn)
                if os.path.isfile(p) and fn.lower().endswith('.png') and T.match_name(fn):
                    k = T.match_name(fn)
                    if k not in self.repl_index or os.path.getmtime(p) > os.path.getmtime(self.repl_index[k]):
                        self.repl_index[k] = p

    def ready_dir(self):
        return self.cfg['ready'] or (os.path.join(self.cfg['replacements'], 'ready') if self.cfg['replacements'] else '')

    # ------------------------------------------------------------ convert tab
    def build_convert(self):
        # draggable divider: the list on the left can be made wider. The divider position is set once the window has
        # its real size (setting it too early collapsed the list on some machines).
        pane = ttk.PanedWindow(self.tab_conv, orient='horizontal')
        pane.pack(fill='both', expand=True, padx=6, pady=6)
        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=1)
        self._sash_done = False

        def place_sash(ev=None):
            if not self._sash_done and pane.winfo_width() > 900:
                self._sash_done = True
                pane.sashpos(0, min(620, pane.winfo_width() // 2))
        pane.bind('<Configure>', place_sash)

        top = ttk.Frame(left)
        top.pack(fill='x')
        ttk.Label(top, text='Which graphic?').pack(side='left')
        self.var_filter = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.var_filter)
        e.pack(side='left', fill='x', expand=True, padx=6)
        self.var_filter.trace_add('write', lambda *a: self.fill_targets())
        self.var_only_files = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text='only with file', variable=self.var_only_files,
                        command=self.fill_targets).pack(side='left')
        cols = ('key', 'desc', 'size', 'status', 'file', 'ready')
        self.tree = ttk.Treeview(left, columns=cols, show='headings', selectmode='browse')
        for c, t, w in (('key', 'Key', 62), ('desc', 'Content', 260), ('size', 'Size', 76), ('status', 'Status', 76),
                        ('file', 'Your file', 90), ('ready', 'Ready', 44)):
            self.tree.heading(c, text=t)
            # stretch off: columns keep the width you drag them to (a horizontal scrollbar appears if needed)
            self.tree.column(c, width=w, minwidth=40, anchor='w', stretch=False)
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        sbx = ttk.Scrollbar(left, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=sbx.set)
        sb.pack(side='right', fill='y')
        sbx.pack(side='bottom', fill='x')
        self.tree.pack(fill='both', expand=True, pady=(6, 0))
        self.tree.tag_configure('has', background='#e4f4e4')
        self.tree.tag_configure('exp', foreground='#8a5a00')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.on_select())

        r = right
        self.lbl_title = ttk.Label(r, text='Select a graphic on the left', font=('Segoe UI', 11, 'bold'))
        self.lbl_title.pack(anchor='w')
        self.lbl_sub = ttk.Label(r, text='', foreground='#555')
        self.lbl_sub.pack(anchor='w')
        row = ttk.Frame(r)
        row.pack(fill='x', pady=(8, 2))
        ttk.Label(row, text='Your PNG:').pack(side='left')
        self.var_file = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_file, state='readonly').pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(row, text='Choose PNG...', command=self.choose_file).pack(side='left')
        opts = ttk.Frame(r)
        opts.pack(fill='x', pady=2)
        self.var_fit = tk.BooleanVar(value=self.cfg['fit'])
        ttk.Checkbutton(opts, text='scale automatically if the size is wrong', variable=self.var_fit,
                        command=self.recheck).pack(side='left')
        self.frm_att = ttk.Frame(opts)
        for lbl, key, lo, hi, inc in (('scale', 'scale', 0.3, 1.5, 0.05), ('shift x', 'dx', -40, 40, 1),
                                      ('shift y', 'dy', -40, 40, 1)):
            ttk.Label(self.frm_att, text=lbl).pack(side='left', padx=(10, 2))
            v = tk.DoubleVar(value=1.0) if key == 'scale' else tk.IntVar(value=0)
            setattr(self, 'var_' + key, v)
            sp = ttk.Spinbox(self.frm_att, from_=lo, to=hi, increment=inc, textvariable=v, width=5,
                             command=self.recheck)
            sp.pack(side='left')
            sp.bind('<Return>', lambda e: self.recheck())
        self.frm_clk = ttk.Frame(opts)
        ttk.Label(self.frm_clk, text='rotate before inserting:').pack(side='left', padx=(10, 4))
        self.var_clock_rot = tk.StringVar(value=ROT_LABELS.get(int(self.cfg.get('clock_rot', 90)), ROT_LABELS[90]))
        cb = ttk.Combobox(self.frm_clk, textvariable=self.var_clock_rot, values=list(ROT_LABELS.values()),
                          state='readonly', width=22)
        cb.pack(side='left')
        cb.bind('<<ComboboxSelected>>', lambda e: (self.update_sub(self.cur_target()), self.recheck()))
        ttk.Label(self.frm_clk, text='(the game shows the frozen clock turned 90 deg counter-clockwise)',
                  foreground='#666').pack(side='left', padx=8)
        self.msg = tk.Text(r, height=6, wrap='word', relief='solid', borderwidth=1, font=('Segoe UI', 9))
        for k, c in COLORS.items():
            self.msg.tag_configure(k, foreground=c)
        self.msg.tag_configure('ok', foreground=COLORS['ok'], font=('Segoe UI', 9, 'bold'))
        self.msg.tag_configure('error', foreground=COLORS['error'], font=('Segoe UI', 9, 'bold'))
        self.msg.configure(state='disabled')
        self.msg.pack(fill='x', pady=6)
        bar = ttk.Frame(r)
        bar.pack(fill='x')
        ttk.Label(bar, text='Preview background:').pack(side='left')
        self.var_bg = tk.StringVar(value='Checkerboard')
        cb = ttk.Combobox(bar, textvariable=self.var_bg, state='readonly', width=13,
                          values=['Checkerboard', 'Black', 'White', 'Green', 'Orange'])
        cb.pack(side='left', padx=6)
        cb.bind('<<ComboboxSelected>>', lambda e: self.show_preview())
        pv = ttk.Frame(r)
        pv.pack(fill='both', expand=True, pady=4)
        self.pv = []
        for i, cap in enumerate(('Original', 'As the game will show it')):
            fr = ttk.Frame(pv)
            fr.pack(side='left', fill='both', expand=True, padx=3)
            ttk.Label(fr, text=cap, foreground='#555').pack()
            lb = ttk.Label(fr, anchor='center')
            lb.pack(fill='both', expand=True)
            self.pv.append(lb)
        bt = ttk.Frame(r)
        bt.pack(fill='x', pady=(4, 0))
        self.btn_quant = ttk.Button(bt, text='Reduce colours so it fits', command=self.apply_quant)
        self.btn_conv = ttk.Button(bt, text='Convert  >  ready folder', command=self.convert)
        self.btn_conv.pack(side='right')
        self.btn_quant.pack(side='right', padx=8)
        self.btn_quant.pack_forget()
        self.btn_conv.state(['disabled'])

    def fill_targets(self):
        sel = self.cur_key()
        self.tree.delete(*self.tree.get_children())
        flt = self.var_filter.get().strip().lower()
        rd = self.ready_dir()
        for t in self.targets:
            f = self.repl_index.get(t.key)
            if flt and flt not in t.key.lower() and flt not in t.desc.lower():
                continue
            if self.var_only_files.get() and not f:
                continue
            ready = '✔' if rd and os.path.isfile(os.path.join(rd, t.key + '.png')) else ''
            tags = (['has'] if f else []) + (['exp'] if t.status != 'verified' else [])
            self.tree.insert('', 'end', iid=t.key, values=(t.key, t.desc, t.size_text, t.status,
                                                          os.path.basename(f) if f else '', ready), tags=tags)
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)

    def cur_key(self):
        s = self.tree.selection()
        return s[0] if s else None

    def cur_target(self):
        k = self.cur_key()
        return next((t for t in self.targets if t.key == k), None) if k else None

    def on_select(self):
        t = self.cur_target()
        if not t:
            return
        self.lbl_title.config(text='%s  -  %s' % (t.key, t.desc))
        self.update_sub(t)
        if t.kind == 'attract':
            self.frm_att.pack(side='left')
        else:
            self.frm_att.pack_forget()
        if t.kind == 'clock':
            self.frm_clk.pack(side='left')
        else:
            self.frm_clk.pack_forget()
        f = self.repl_index.get(t.key, '')
        self.var_file.set(f)
        if t.kind == 'attract':
            self.load_attract_params(f)
        self.result = None
        self.btn_quant.pack_forget()
        self.btn_conv.state(['disabled'])
        self.set_msgs([('info', 'Choose your PNG (or use the one found in the replacements folder).')] if not f else [])
        self.show_original()
        self.show_preview()
        if f:
            self.recheck()

    def choose_file(self):
        t = self.cur_target()
        if not t:
            messagebox.showinfo('Convert', 'Select a graphic on the left first.')
            return
        init = self.cfg['replacements'] if os.path.isdir(self.cfg['replacements']) else (self.cfg['last_dir'] or None)
        p = filedialog.askopenfilename(initialdir=init, title='Your PNG for %s' % t.key,
                                       filetypes=[('PNG image', '*.png'), ('All files', '*.*')])
        if p:
            self.var_file.set(os.path.normpath(p))
            self.cfg['last_dir'] = os.path.dirname(p)
            if t.kind == 'attract':
                self.load_attract_params(p)
            self.recheck()

    def iso_for_checks(self):
        """Input ISO (tab 2) enables the real OPENING.GRC size check for OPENING entries."""
        var = getattr(self, 'var_iso_in', None)
        p = var.get().strip() if var is not None else self.cfg.get('iso_in', '')
        return p if p and os.path.isfile(p) else None

    def update_sub(self, t):
        if t.kind == 'clock':
            w, h = T.CLOCK_SIZE if self.clock_rot() % 180 == 0 else T.CLOCK_SIZE[::-1]
            text = ('Make the PNG exactly %d x %d px (width x height) for this rotation: then nothing is scaled. '
                    'Other sizes are fitted in. 1-bit alpha, flat colours (8 or fewer) compress best.'
                    % (w, h))
        else:
            text = 'Needs %s, %s%s' % (t.size_text, t.fmt or 'ARGB1555 (1-bit alpha)',
                                       '')
        self.lbl_sub.config(text=text, wraplength=620, justify='left')

    def clock_rot(self):
        for deg, lab in ROT_LABELS.items():
            if lab == self.var_clock_rot.get():
                return deg
        return 0

    def attract_key(self, path):
        return os.path.normcase(os.path.abspath(path)) if path else ''

    def load_attract_params(self, path):
        """Scale / shift are remembered per PNG file; a file never seen before starts at 1.0 / 0 / 0."""
        sc, dx, dy = (self.cfg.get('attract_by_file') or {}).get(self.attract_key(path), (1.0, 0, 0))
        self.var_scale.set(sc)
        self.var_dx.set(dx)
        self.var_dy.set(dy)

    def attract_params(self):
        try:
            return float(self.var_scale.get()), int(self.var_dx.get()), int(self.var_dy.get())
        except (tk.TclError, ValueError):
            return 1.0, 0, 0

    def recheck(self, allow_quant=False):
        t, f = self.cur_target(), self.var_file.get()
        self.cfg['fit'] = bool(self.var_fit.get())
        if not t or not f:
            return
        if t.kind == 'attract':
            sc, dx, dy = self.attract_params()
            self.cfg.setdefault('attract_by_file', {})[self.attract_key(f)] = [sc, dx, dy]
        else:
            sc, dx, dy = 1.0, 0, 0
        self.check_id += 1
        cid = self.check_id
        self.set_msgs([('info', 'checking ...')])
        self.btn_conv.state(['disabled'])
        fit = self.var_fit.get()
        iso = self.iso_for_checks()
        rot = self.clock_rot() if t.kind == 'clock' else 0
        if t.kind == 'clock':
            self.cfg['clock_rot'] = rot
        self.bg(lambda: C.check_png(t, f, fit, allow_quant, sc, dx, dy, iso_path=iso, rot=rot),
                lambda r, e: self.checked(cid, r, e))

    def checked(self, cid, r, err):
        if cid != self.check_id:
            return
        if err:
            self.set_msgs([('error', 'internal error: %s' % err)])
            traceback.print_exception(type(err), err, err.__traceback__)
            return
        self.result = r
        self.set_msgs(r.msgs)
        self.show_preview()
        self.btn_quant.pack_forget()
        if r.needs_quant or r.stream_over:
            self.btn_quant.pack(side='right', padx=8)
        self.btn_conv.state(['!disabled'] if r.ok else ['disabled'])

    def apply_quant(self):
        self.recheck(allow_quant=True)

    def set_msgs(self, msgs):
        self.msg.configure(state='normal')
        self.msg.delete('1.0', 'end')
        icons = {'error': 'ERROR  ', 'warn': 'Warning  ', 'ok': 'OK  ', 'info': ''}
        order = {'error': 0, 'warn': 1, 'ok': 2, 'info': 3}
        for lv, text in sorted(msgs, key=lambda m: order[m[0]]):
            self.msg.insert('end', icons[lv] + text + '\n', lv)
        self.msg.configure(state='disabled')

    def show_original(self):
        t = self.cur_target()
        p = self.orig_index.get(t.key) if t else None
        self.orig_img = None
        if p:
            try:
                self.orig_img = Image.open(p).convert('RGBA')
            except Exception:
                self.orig_img = None

    def show_preview(self):
        bgn = self.var_bg.get()
        for i, im in enumerate((getattr(self, 'orig_img', None), self.result.game if self.result else None)):
            if im is None:
                self.photo[i] = None
                self.pv[i].config(image='', text='(no original found)' if i == 0 else '(no preview yet)')
            else:
                self.photo[i] = render_preview(im, bgn)
                self.pv[i].config(image=self.photo[i], text='')

    def convert(self):
        r, t = self.result, self.cur_target()
        if not (r and r.ok and t):
            return
        rd = self.ready_dir()
        if not rd:
            rd = filedialog.askdirectory(title='Ready folder (output of the conversion)')
            if not rd:
                return
            rd = os.path.normpath(rd)
            self.var_ready.set(rd)
        os.makedirs(rd, exist_ok=True)
        out = os.path.join(rd, t.key + '.png')
        r.final.save(out)
        self.fill_targets()
        self.pull_settings()
        self.set_msgs(r.msgs + [('ok', 'Saved %s' % out)])

    # ------------------------------------------------------------ patch tab
    def build_patch(self):
        f = ttk.Frame(self.tab_patch, padding=10)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text='Choose your own KOF XI disc image (JP or US), tick what you want and click Patch. '
                  'A new ISO is created; your original is never changed.', foreground='#444').pack(anchor='w', pady=(0, 6))
        top = ttk.Frame(f)
        top.pack(fill='x')
        top.columnconfigure(1, weight=1)
        self.folder_row(top, 0, 'Input ISO (JP or US, never modified):', 'iso_in', is_file=True)
        self.lbl_variant = ttk.Label(top, text='', foreground='#444')
        self.lbl_variant.grid(row=3, column=0, columnspan=2, sticky='w')
        self.folder_row(top, 1, 'Output ISO (new file):', 'iso_out', is_file=True, save=True)
        self.var_pfolder = tk.StringVar()
        ttk.Label(top, text='Graphics folder (optional):').grid(row=2, column=0, sticky='w', padx=(0, 8), pady=4)
        ttk.Entry(top, textvariable=self.var_pfolder).grid(row=2, column=1, sticky='ew', pady=4)
        ttk.Button(top, text='Browse...', command=self.browse_pfolder).grid(row=2, column=2, padx=(8, 0))
        ttk.Button(top, text='Rescan', command=self.scan_patch).grid(row=2, column=3, padx=(6, 0))
        ttk.Button(top, text='Untick all graphics', command=lambda: self.tick_all(False)).grid(row=3, column=3, padx=(6, 0),
                                                                                    pady=(4, 0))
        ttk.Button(top, text='Tick all graphics', command=lambda: self.tick_all(True)).grid(row=3, column=2, sticky='e',
                                                                                 pady=(4, 0))
        self.var_auto = tk.BooleanVar(value=self.cfg['auto_fix'])
        ttk.Checkbutton(f, text='Fix graphics automatically while patching (resize, reduce colours). '
                        'Normally you convert them on tab 1 first.', variable=self.var_auto).pack(anchor='w', pady=(4, 0))
        hf = ttk.LabelFrame(f, text='Game hacks')
        hf.pack(fill='x', pady=(8, 0))
        self.hack_vars = {}
        self.hack_boxes = {}
        self.hack_variants = {}                 # key -> disc versions that have this hack
        MENU_HACKS = ('clockspin',)             # shown in the main menu frame below instead of here
        grid_i = 0
        for key, (label, desc, variants) in H.all_hack_keys().items():
            v = tk.BooleanVar(value=key in self.cfg.get('hacks', []))
            v.trace_add('write', lambda *a: self.pull_settings())
            self.hack_vars[key] = v
            self.hack_variants[key] = variants
            if key in MENU_HACKS:
                continue
            i, grid_i = grid_i, grid_i + 1
            cb = ttk.Checkbutton(hf, text=label, variable=v)
            cb.grid(row=i // 2, column=(i % 2) * 2, sticky='w', padx=(10, 4), pady=2)
            self.hack_boxes[key] = cb
            ttk.Label(hf, text=desc, foreground='#666', wraplength=330).grid(row=i // 2, column=(i % 2) * 2 + 1,
                                                                            sticky='w', padx=(0, 14))
        mf = ttk.LabelFrame(f, text='Main menu colours and animations (JP and US)')
        mf.pack(fill='x', pady=(8, 0))
        self.var_ui_color = tk.StringVar(value=self.cfg.get('ui_color', ''))
        self.var_frame_color = tk.StringVar(value=self.cfg.get('frame_color', ''))
        self.var_margin_color = tk.StringVar(value=self.cfg.get('margin_color', ''))
        self.var_font_orange = tk.StringVar(value=self.cfg.get('font_orange', ''))
        self.var_font_teal = tk.StringVar(value=self.cfg.get('font_teal', ''))
        self.cv_swatch = {}
        for row, (name, var, label, hint) in enumerate((
                ('ui', self.var_ui_color, 'UI colour (hex):',
                 'Replaces the orange of the menu (buttons, selected row, header, frame line, ring text), e.g. cb0608. '
                 'Empty = keep orange.'),
                ('frame', self.var_frame_color, 'Frame colour (hex):',
                 'The grey border around the menu windows (default aaaaaa). Empty = keep grey.'),
                ('margin', self.var_margin_color, 'Outer margin (hex):',
                 'The white area outside the frame (all menus). Empty = keep white.'),
                ('font_orange', self.var_font_orange, 'Orange alphabet (hex):',
                 'The orange menu font (game option labels, key setting, memory card dialogs ...). Empty = keep orange.'),
                ('font_teal', self.var_font_teal, 'Turquoise alphabet (hex):',
                 'The turquoise menu font (values like NORMAL, ON, OFF ...). Empty = keep turquoise.'))):
            ttk.Label(mf, text=label).grid(row=row, column=0, sticky='w', padx=(10, 6), pady=3)
            ttk.Entry(mf, textvariable=var, width=10).grid(row=row, column=1, sticky='w')
            cv = tk.Canvas(mf, width=300 if name == 'ui' else 90, height=26, highlightthickness=1,
                           highlightbackground='#999')
            cv.grid(row=row, column=2, sticky='w', padx=10, pady=3)
            self.cv_swatch[name] = (cv, var)
            ttk.Button(mf, text='Pick...', width=7, command=lambda v=var: self.pick_color(v)).grid(row=row, column=3,
                                                                                                  sticky='w')
            ttk.Label(mf, text=hint, foreground='#666', wraplength=560).grid(row=row, column=4, sticky='w', padx=10)
            var.trace_add('write', lambda *a: self.update_swatches())
        self.var_hide_anim = tk.BooleanVar(value=bool(self.cfg.get('hide_anim')))
        ttk.Checkbutton(mf, text='disable main menu animations (swirly 3D background, the rotating KOF XI ring text '
                        'and the drifting dots)', variable=self.var_hide_anim,
                        command=self.pull_settings).grid(row=5, column=0, columnspan=5, sticky='w', padx=10, pady=(4, 0))
        self.var_black_bg = tk.BooleanVar(value=bool(self.cfg.get('black_bg')))
        ttk.Checkbutton(mf, text='black menu background (inside the frame, all menus; instead of white). Other inner '
                        'colours are not possible: the white box has no editable colour.', variable=self.var_black_bg,
                        command=self.pull_settings).grid(row=6, column=0, columnspan=5, sticky='w', padx=10, pady=(0, 6))
        if 'clockspin' in self.hack_vars:
            ttk.Checkbutton(mf, text='no clock spin (the main menu clock stays still when the cursor moves; JP only)',
                            variable=self.hack_vars['clockspin']).grid(row=7, column=0, columnspan=5, sticky='w', padx=10,
                                                                      pady=(0, 6))
        self.update_swatches()
        cols = ('use', 'key', 'file', 'desc', 'status')
        ttk.Label(f, text='Graphics to patch (only if you chose a graphics folder above):',
                  foreground='#444').pack(anchor='w', pady=(8, 0))
        self.ptree = ttk.Treeview(f, columns=cols, show='headings', height=6, selectmode='none')
        for c, t, w in (('use', 'Patch', 50), ('key', 'Key', 70), ('file', 'File', 230), ('desc', 'Content', 260),
                        ('status', 'Check', 380)):
            self.ptree.heading(c, text=t)
            self.ptree.column(c, width=w, anchor='w' if c != 'use' else 'center', stretch=(c == 'status'))
        self.ptree.tag_configure('bad', foreground=COLORS['error'])
        self.ptree.tag_configure('warn', foreground=COLORS['warn'])
        self.ptree.pack(fill='x', pady=6)
        self.ptree.bind('<Button-1>', self.toggle_row)
        row = ttk.Frame(f)
        row.pack(fill='x')
        self.btn_patch = ttk.Button(row, text='Patch  >  create new ISO', command=self.patch)
        self.btn_patch.pack(side='right')
        self.progress = ttk.Progressbar(row, mode='determinate')
        self.progress.pack(side='left', fill='x', expand=True, padx=(0, 10))
        self.log = tk.Text(f, height=8, wrap='word', relief='solid', borderwidth=1, font=('Consolas', 9))
        self.log.configure(state='disabled')
        self.log.pack(fill='both', expand=True, pady=(6, 0))
        self.var_iso_in.trace_add('write', lambda *a: self.default_out())
        self.var_iso_in.trace_add('write', lambda *a: self.update_variant())
        self.update_variant()
        self.var_pfolder.set(self.ready_dir())
        self.scan_patch()

    def pick_color(self, var):
        from tkinter import colorchooser
        cur = M.parse_color(var.get())
        res = colorchooser.askcolor(color='#%02x%02x%02x' % cur if cur else None, title='Pick a colour')
        if res and res[1]:
            var.set(res[1].lstrip('#').lower())

    def update_swatches(self):
        for name, (cv, var) in self.cv_swatch.items():
            txt = var.get().strip()
            cv.delete('all')
            w = int(cv['width'])
            c = M.parse_color(txt) if txt else None
            if not txt:
                cv.create_text(w // 2, 13, text='no change', fill='#888')
            elif not c:
                cv.create_text(w // 2, 13, text='6 hex digits, e.g. cb0608', fill=COLORS['error'])
            elif name == 'ui':
                cv.create_rectangle(0, 0, 90, 26, fill='#%02x%02x%02x' % c, outline='')
                for i, g in enumerate(M.gradient_preview(c, 7)):   # the button shine: base colour towards light
                    cv.create_rectangle(90 + i * 30, 0, 120 + i * 30, 26, fill='#%02x%02x%02x' % g, outline='')
                cv.create_text(45, 13, text='main', fill='white')
            else:
                cv.create_rectangle(0, 0, w, 26, fill='#%02x%02x%02x' % c, outline='')
        self.pull_settings()

    def on_tab(self, ev=None):
        if self.nb.select() == str(self.tab_patch):
            if not self.var_pfolder.get().strip():
                self.var_pfolder.set(self.ready_dir())
            self.scan_patch()

    def sig_diff(self, a, b):
        """Human readable difference of two folder_sig() values."""
        if a is None:
            return 'first scan'
        parts = []
        if a[0] != b[0]:
            parts.append('folder')
        if a[2] != b[2]:
            parts.append('input ISO')
        if a[3] != b[3]:
            parts.append('automatic fixes option')
        old, new = {x[0]: x for x in a[1]}, {x[0]: x for x in b[1]}
        for fn in sorted(set(old) | set(new)):
            if fn not in old:
                parts.append('new file ' + fn)
            elif fn not in new:
                parts.append('removed ' + fn)
            elif old[fn] != new[fn]:
                parts.append('modified ' + fn)
        return ', '.join(parts) or 'unknown'

    def folder_sig(self):
        """Fingerprint of the patch folder (names, sizes, times of the PNGs) and the input ISO."""
        folder = self.var_pfolder.get().strip() or self.ready_dir()
        sig = []
        if folder and os.path.isdir(folder):
            for fn in sorted(os.listdir(folder)):
                p = os.path.join(folder, fn)
                if fn.lower().endswith('.png') and os.path.isfile(p):
                    st = os.stat(p)
                    sig.append((fn, st.st_size, st.st_mtime_ns))
        return (folder, tuple(sig), self.iso_for_checks(), bool(self.var_auto.get()))

    def browse_pfolder(self):
        p = filedialog.askdirectory(initialdir=self.var_pfolder.get() or self.cfg['last_dir'] or None,
                                    title='Folder with converted PNGs')
        if p:
            self.var_pfolder.set(os.path.normpath(p))
            self.scan_patch()

    def disc_variant(self):
        """'JP' / 'US' / None for the input ISO of tab 2."""
        p = self.var_iso_in.get().strip()
        if not p or not os.path.isfile(p):
            return None
        return G.detect_variant(p)

    def update_variant(self):
        """Show which disc version the input ISO is and enable only the hacks that exist for it."""
        p = self.var_iso_in.get().strip()
        v = self.disc_variant()
        if not p:
            text = 'Choose the input ISO: the tool detects the JP (SLPS-25660) or US (SLUS-21687) disc by itself.'
        elif not os.path.isfile(p):
            text = 'File not found.'
        elif v is None:
            text = 'Not a KOF XI PS2 disc this tool knows (expected the JP SLPS-25660 or the US SLUS-21687).'
        else:
            text = 'Detected: %s disc.' % ('Japanese (SLPS-25660)' if v == 'JP' else 'US (SLUS-21687)')
            n = [k for k, vs in self.hack_variants.items() if v not in vs]
            if n:
                text += '  Not available for this disc: ' + ', '.join(n) + '.'
        self.lbl_variant.config(text=text)
        for key, cb in self.hack_boxes.items():
            ok = v is None or v in self.hack_variants[key]
            cb.state(['!disabled'] if ok else ['disabled'])

    def default_out(self):
        src = self.var_iso_in.get().strip()
        if src and os.path.isfile(src) and not self.var_iso_out.get().strip():
            stem, ext = os.path.splitext(src)
            self.var_iso_out.set(stem + ' Mad Gear' + (ext or '.iso'))

    def scan_patch(self):
        self.scan_sig = self.folder_sig()
        self.ptree.delete(*self.ptree.get_children())
        self.patch_rows = {}
        folder = self.var_pfolder.get().strip() or self.ready_dir()
        if not folder:
            self.log_add('No graphics folder set: only the hacks and menu options will be patched.')
            return
        if not os.path.isdir(folder):
            self.log_add('The folder with the converted PNGs does not exist: %s' % folder)
            return
        found, dup = C.scan_folder(folder)
        cat = T.by_key()
        for k, p in found:
            t = cat[k.upper()]
            self.patch_rows[t.key] = {'path': p, 'use': False, 'ok': None}
            self.ptree.insert('', 'end', iid=t.key, values=('☑' if t.key not in self.untick else '☐', t.key,
                                                            os.path.basename(p), t.desc, 'checking ...'))
        for k, p1, p2 in dup:
            self.log_add('Note: several files match %s, using %s' % (k, os.path.basename(p2)))
        if not found:
            self.log_add('No known graphic names found in %s (expected e116.png, LOGO04.png, attract.png, ...).'
                         % folder)
        auto = bool(self.var_auto.get())
        att = self.attract_params()
        iso = self.iso_for_checks()
        # One worker runs the checks one after the other: a thread per file (all at once) used up to 2.4 GB of memory.
        # A newer scan makes an older one stop before its next file.
        self.scan_gen = getattr(self, 'scan_gen', 0) + 1
        gen = self.scan_gen
        tasks = []
        for k, p in found:
            t = cat[k.upper()]
            prm = att if t.kind == 'attract' else (1.0, 0, 0)
            tasks.append((lambda t=t, p=p, prm=prm: C.check_png(t, p, auto, auto, *prm, iso_path=iso),
                          lambda r, e, key=t.key: self.scanned(key, r, e)))

        def work():
            for fn, done in tasks:
                if self.scan_gen != gen:
                    return
                try:
                    res, err = fn(), None
                except BaseException as e:      # SystemExit carries our own error texts
                    res, err = None, e
                self.q.put(('call', done, res, err))
        if tasks:
            threading.Thread(target=work, daemon=True).start()

    def scanned(self, key, r, err):
        row = self.patch_rows.get(key)
        if row is None or not self.ptree.exists(key):
            return
        if err or r is None:
            st, tag, ok = 'internal error: %s' % err, 'bad', False
        elif r.errors:
            st, tag, ok = r.errors[0], 'bad', False
        elif r.needs_quant:
            st, tag, ok = 'needs a colour reduction: convert it on tab 1 first', 'bad', False
        else:
            warns = [t for lv, t in r.msgs if lv == 'warn']
            st = ('OK, but: ' + warns[0]) if warns else 'OK'
            tag, ok = ('warn' if warns else ''), True
        row['ok'], row['use'] = ok, ok and key not in self.untick
        vals = list(self.ptree.item(key, 'values'))
        vals[0], vals[4] = ('☑' if row['use'] else '☐') if ok else '☒', st
        self.ptree.item(key, values=vals, tags=(tag,) if tag else ())
        if self.retry_patch and all(r2['ok'] is not None for r2 in self.patch_rows.values()):
            self.retry_patch = False
            self.root.after(150, self.patch)

    def set_row_use(self, key, use):
        row = self.patch_rows.get(key)
        if not row:
            return
        (self.untick.discard if use else self.untick.add)(key)
        if row['ok'] is False:
            return
        row['use'] = bool(use) and row['ok'] is not False
        vals = list(self.ptree.item(key, 'values'))
        vals[0] = '☑' if use else '☐'
        self.ptree.item(key, values=vals)

    def toggle_row(self, ev):
        key = self.ptree.identify_row(ev.y)
        if not key or self.ptree.identify_column(ev.x) != '#1':
            return
        row = self.patch_rows.get(key)
        if not row or row['ok'] is False:
            return
        self.set_row_use(key, key in self.untick)      # works while the check is still running, too

    def tick_all(self, use):
        for key, row in self.patch_rows.items():
            if row['ok'] is not False:
                self.set_row_use(key, use)

    def log_add(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def patch(self):
        if self.busy:
            return
        self.pull_settings()
        cur = self.folder_sig()
        if cur != self.scan_sig:
            why = self.sig_diff(self.scan_sig, cur)
            self.scan_patch()
            if self.auto_retry:
                self.log_add('The folder changed again (%s): list refreshed. Check it, then click Patch again.' % why)
                self.auto_retry = False
            else:
                self.log_add('Changes since the last scan (%s): re-checking the files, patching continues '
                             'automatically ...' % why)
                self.auto_retry = self.retry_patch = True
                if not any(r['ok'] is None for r in self.patch_rows.values()):
                    # nothing to check (no graphics folder / no PNGs): no check will call back, so continue now
                    self.retry_patch = False
                    self.root.after(150, self.patch)
            return
        self.auto_retry = False
        if any(r['ok'] is None for r in self.patch_rows.values()):
            self.log_add('Still checking the files: patching starts automatically as soon as the checks are done.')
            self.retry_patch = True
            return
        src, dst = self.cfg['iso_in'], self.cfg['iso_out']
        jobs = [(k, r['path']) for k, r in self.patch_rows.items() if r['use']]
        if not src or not os.path.isfile(src):
            messagebox.showerror('Patch', 'Choose the input ISO first.')
            return
        if not dst:
            messagebox.showerror('Patch', 'Choose the output ISO (a new file name).')
            return
        variant = self.disc_variant()
        if variant is None:
            messagebox.showerror('Patch', 'The input ISO is not a JP (SLPS-25660) or US (SLUS-21687) KOF XI disc.')
            return
        ticked = [k for k, v in self.hack_vars.items() if v.get()]
        hacks = [k for k in ticked if variant in self.hack_variants[k]]
        if len(hacks) != len(ticked):
            names = ', '.join(k for k in ticked if k not in hacks)
            msg = ('These ticked hacks do not exist for the %s disc and are skipped: %s. '
                   'Continue without them?' % (variant, names))
            if not messagebox.askyesno('Patch', msg):
                return
        ui_text = self.var_ui_color.get().strip()
        ui_color = M.parse_color(ui_text) if ui_text else None
        if ui_text and not ui_color:
            messagebox.showerror('Patch', 'The UI colour needs 6 hex digits, e.g. cb0608 (or leave it empty).')
            return
        hide_anim = bool(self.var_hide_anim.get())
        black_bg = bool(self.var_black_bg.get())
        fr_text = self.var_frame_color.get().strip()
        frame_color = M.parse_color(fr_text) if fr_text else None
        if fr_text and not frame_color:
            messagebox.showerror('Patch', 'The frame colour needs 6 hex digits, e.g. 202020 (or leave it empty).')
            return
        fo_text = self.var_font_orange.get().strip()
        ft_text = self.var_font_teal.get().strip()
        font_orange = M.parse_color(fo_text) if fo_text else None
        font_teal = M.parse_color(ft_text) if ft_text else None
        if (fo_text and not font_orange) or (ft_text and not font_teal):
            messagebox.showerror('Patch', 'The alphabet colours need 6 hex digits, e.g. cb0608 (or leave them empty).')
            return
        mg_text = self.var_margin_color.get().strip()
        margin_color = M.parse_color(mg_text) if mg_text else None
        if mg_text and not margin_color:
            messagebox.showerror('Patch', 'The outer margin colour needs 6 hex digits, e.g. 3050a0 (or leave it empty).')
            return
        skipped = [k for k, r in self.patch_rows.items() if r['ok'] is False]
        if skipped and not messagebox.askyesno(
                'Patch', 'These files have problems and will NOT be patched:\n\n%s\n\n(see the Check column)\n\n'
                'Continue without them?' % ', '.join(skipped)):
            return
        if not jobs and not hacks and not ui_color and not hide_anim and not black_bg and not frame_color and not margin_color and not font_orange and not font_teal:
            messagebox.showerror('Patch', 'Nothing selected: tick a graphic, a game hack, a UI colour or the menu '
                                 'animations option. (Graphics: convert them on tab 1 first, then rescan here.)')
            return
        if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
            messagebox.showerror('Patch', 'Input and output must be different files.')
            return
        force = False
        if os.path.exists(dst):
            if not messagebox.askyesno('Patch', '%s already exists.\nOverwrite it? (Close the emulator first.)' % dst):
                return
            force = True
        if not messagebox.askyesno('Patch', 'Create %s\nfrom %s\nwith %d graphic(s): %s\nand %d hack(s): %s\n\n'
                                   'UI colour: %s, main menu animations: %s, black background: %s, '
                                   'frame colour: %s, outer margin: %s, orange alphabet: %s, turquoise alphabet: %s\n\n'
                                   'This copies about 2.5 GB. Continue?'
                                   % (os.path.basename(dst), os.path.basename(src), len(jobs),
                                      ', '.join(k for k, _ in jobs) or '-', len(hacks), ', '.join(hacks) or '-',
                                      ui_text or 'unchanged', 'switched off' if hide_anim else 'unchanged',
                                      'yes' if black_bg else 'no', fr_text or 'unchanged', mg_text or 'unchanged',
                                      fo_text or 'unchanged', ft_text or 'unchanged')):
            return
        self.busy = True
        self.btn_patch.state(['disabled'])
        self.progress['value'] = 0
        auto = bool(self.var_auto.get())
        sc, dx, dy = self.attract_params()

        def run():
            C.apply_jobs(src, dst, jobs, fit=auto, allow_quant=auto, force=force, scale=sc, dx=dx, dy=dy, hacks=hacks, ui_color=ui_color, hide_anim=hide_anim, black_bg=black_bg, frame_color=frame_color,
                         margin_color=margin_color, font_orange=font_orange, font_teal=font_teal,
                         log=lambda s: self.q.put(('log', s)),
                         progress=lambda d, t: self.q.put(('progress', d, t)))

        def done(res, err):
            self.busy = False
            self.btn_patch.state(['!disabled'])
            if err is None:
                self.progress['value'] = 100
                messagebox.showinfo('Patch', 'Done.\n\n%s' % dst)
            else:
                msg = str(err) if isinstance(err, SystemExit) else '%s: %s' % (type(err).__name__, err)
                self.log_add('FAILED: ' + msg)
                if not isinstance(err, SystemExit):
                    self.log_add(''.join(traceback.format_exception(type(err), err, err.__traceback__)))
                messagebox.showerror('Patch failed', msg)
        self.bg(run, done)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use('vista')
    except tk.TclError:
        pass
    def report(exc, val, tb):
        # an error inside a button callback used to be swallowed (windowed exe has no console): show it instead
        text = ''.join(traceback.format_exception(exc, val, tb))
        try:
            messagebox.showerror('Internal error', '%s: %s\n\n%s' % (exc.__name__, val, text[-1500:]))
        except Exception:
            pass
    root.report_callback_exception = report
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
