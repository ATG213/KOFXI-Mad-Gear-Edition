#!/usr/bin/env python3
"""KOF XI Mad Gear Edition self-patcher (PS2, Japanese disc SLPS-25660).

Select YOUR OWN dump of the Japanese disc image; the patcher writes a NEW ISO next to it (the original
is only read) and verifies the result.  No game data is included, only the byte differences of the mod.
"""
import hashlib
import os
import struct
import sys
import threading
import zlib

MAGIC = b'KMGP1\0'
VERSION = '1.5'
TITLE = 'KOF XI Mad Gear Edition Patcher v%s' % VERSION


def resource(name):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def load_payload():
    data = open(resource('payload.bin'), 'rb').read()
    if not data.startswith(MAGIC):
        raise RuntimeError('payload.bin is damaged')
    p = len(MAGIC)
    size, count = struct.unpack_from('<QI', data, p)
    p += 12
    md5_orig, md5_mg = data[p:p + 16].hex(), data[p + 16:p + 32].hex()
    body = zlib.decompress(data[p + 32:])
    runs, q = [], 0
    for _ in range(count):
        off, ln = struct.unpack_from('<QI', body, q)
        q += 12
        runs.append((off, body[q:q + ln]))
        q += ln
    return size, md5_orig, md5_mg, runs


def md5_file(path, progress, label):
    h = hashlib.md5()
    total = os.path.getsize(path)
    done = 0
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
            done += len(b)
            progress(label, done / total)
    return h.hexdigest()


def patch(src, dst, log, progress):
    size, md5_orig, md5_mg, runs = load_payload()
    if os.path.abspath(src) == os.path.abspath(dst):
        raise RuntimeError('output must be a new file')
    if os.path.getsize(src) != size:
        raise RuntimeError('wrong file size (%d bytes, expected %d). This patch needs the Japanese disc '
                           '(SLPS-25660) as a plain 2048-byte-sector .iso.' % (os.path.getsize(src), size))
    log('Checking the source image ...')
    got = md5_file(src, progress, 'Checking source')
    if got != md5_orig:
        raise RuntimeError('This is not the expected Japanese disc dump (MD5 %s, expected %s).\n'
                           'A different dump or an already modified ISO cannot be patched.' % (got, md5_orig))
    log('Source OK. Writing %s ...' % dst)
    with open(src, 'rb') as fi, open(dst, 'wb') as fo:
        done = 0
        while True:
            b = fi.read(1 << 22)
            if not b:
                break
            fo.write(b)
            done += len(b)
            progress('Copying', done / size)
        for off, data in runs:
            fo.seek(off)
            fo.write(data)
    log('Verifying the result ...')
    got = md5_file(dst, progress, 'Verifying')
    if got != md5_mg:
        os.remove(dst)
        raise RuntimeError('Verification failed (MD5 %s); the output was deleted.' % got)
    log('Done. Verified: %s' % dst)


def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title(TITLE)
    root.geometry('620x330')
    src_v, dst_v = tk.StringVar(), tk.StringVar()
    pad = {'padx': 8, 'pady': 4}

    def row(r, label, var, cmd):
        ttk.Label(root, text=label).grid(row=r, column=0, sticky='w', **pad)
        ttk.Entry(root, textvariable=var, width=52).grid(row=r, column=1, **pad)
        ttk.Button(root, text='Browse...', command=cmd).grid(row=r, column=2, **pad)

    def pick_src():
        p = filedialog.askopenfilename(title='Japanese KOF XI disc image', filetypes=[('ISO', '*.iso'), ('All', '*.*')])
        if p:
            src_v.set(p)
            if not dst_v.get():
                dst_v.set(os.path.join(os.path.dirname(p), 'KOFXI Mad Gear Edition v%s.iso' % VERSION))

    def pick_dst():
        p = filedialog.asksaveasfilename(title='Output ISO', defaultextension='.iso', filetypes=[('ISO', '*.iso')])
        if p:
            dst_v.set(p)

    row(0, 'Japanese KOF XI ISO:', src_v, pick_src)
    row(1, 'Output ISO (new file):', dst_v, pick_dst)
    status = tk.StringVar(value='Choose your own Japanese disc dump (SLPS-25660), then press Patch.')
    ttk.Label(root, textvariable=status, wraplength=590).grid(row=2, column=0, columnspan=3, sticky='w', **pad)
    bar = ttk.Progressbar(root, length=590, maximum=1.0)
    bar.grid(row=3, column=0, columnspan=3, **pad)
    logbox = tk.Text(root, height=7, width=76, state='disabled')
    logbox.grid(row=4, column=0, columnspan=3, **pad)
    btn = ttk.Button(root, text='Patch')
    btn.grid(row=5, column=1, **pad)

    def log(t):
        def f():
            logbox.configure(state='normal')
            logbox.insert('end', t + '\n')
            logbox.see('end')
            logbox.configure(state='disabled')
            status.set(t)
        root.after(0, f)

    def progress(label, frac):
        root.after(0, lambda: (bar.configure(value=frac), status.set('%s ... %d%%' % (label, int(frac * 100)))))

    def go():
        s, d = src_v.get().strip(), dst_v.get().strip()
        if not s or not d:
            messagebox.showwarning(TITLE, 'Choose the source and output files first.')
            return
        if os.path.exists(d) and not messagebox.askyesno(TITLE, '%s exists. Overwrite?' % d):
            return
        btn.state(['disabled'])

        def work():
            try:
                patch(s, d, log, progress)
                root.after(0, lambda: messagebox.showinfo(TITLE, 'Finished. The new ISO is ready:\n%s' % d))
            except Exception as e:
                msg = str(e)
                log('ERROR: ' + msg)
                root.after(0, lambda: messagebox.showerror(TITLE, msg))
            finally:
                root.after(0, lambda: btn.state(['!disabled']))
        threading.Thread(target=work, daemon=True).start()

    btn.configure(command=go)
    root.mainloop()


def main(argv):
    if len(argv) >= 3:      # command line: madgear_patcher SRC.iso DST.iso
        patch(argv[1], argv[2], print, lambda l, f: print('\r%s %3d%%' % (l, int(f * 100)), end='', flush=True))
        return 0
    run_gui()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
