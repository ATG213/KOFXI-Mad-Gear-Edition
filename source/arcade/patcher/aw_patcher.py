#!/usr/bin/env python3
"""KOF XI Mad Gear Edition self-patcher (Atomiswave / AW Multi).

Select YOUR OWN ax3201p01.fmem1 (the unmodified KOF XI MAME dump); the patcher writes a NEW hacked
ax3201p01.fmem1 (the original is only read) and verifies the result. No game data is included, only the
byte differences of the mod.
"""
import hashlib, os, struct, sys, threading, zlib

MAGIC = b'KMGA1\0'
VERSION = '1.1'
TITLE = 'KOF XI Mad Gear Edition Patcher (Atomiswave) v%s' % VERSION


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
    md5_orig, md5_mod = data[p:p + 16].hex(), data[p + 16:p + 32].hex()
    body = zlib.decompress(data[p + 32:])
    runs, q = [], 0
    for _ in range(count):
        off, ln = struct.unpack_from('<QI', body, q)
        q += 12
        runs.append((off, body[q:q + ln]))
        q += ln
    return size, md5_orig, md5_mod, runs


def patch(src, dst, log):
    size, md5_orig, md5_mod, runs = load_payload()
    if os.path.abspath(src) == os.path.abspath(dst):
        raise RuntimeError('output must be a new file')
    if os.path.getsize(src) != size:
        raise RuntimeError('wrong file size (%d bytes, expected %d). This patch needs the original '
                           'ax3201p01.fmem1 of The King of Fighters XI.' % (os.path.getsize(src), size))
    log('Checking the source file ...')
    with open(src, 'rb') as f:
        buf = bytearray(f.read())
    got = hashlib.md5(buf).hexdigest()
    if got != md5_orig:
        raise RuntimeError('This is not the expected original ax3201p01.fmem1 (MD5 %s, expected %s).\n'
                           'A different dump or an already modified file cannot be patched.' % (got, md5_orig))
    log('Source OK. Applying %d patch runs ...' % len(runs))
    for off, data in runs:
        buf[off:off + len(data)] = data
    if hashlib.md5(buf).hexdigest() != md5_mod:
        raise RuntimeError('Verification failed; nothing was written.')
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(buf)
    log('Done. Verified: %s' % dst)
    log('CRC32 %08x  SHA1 %s' % (zlib.crc32(buf), hashlib.sha1(buf).hexdigest()))


def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title(TITLE)
    root.geometry('640x300')
    src_v, dst_v = tk.StringVar(), tk.StringVar()
    pad = {'padx': 8, 'pady': 4}

    def row(r, label, var, cmd):
        ttk.Label(root, text=label).grid(row=r, column=0, sticky='w', **pad)
        ttk.Entry(root, textvariable=var, width=52).grid(row=r, column=1, **pad)
        ttk.Button(root, text='Browse...', command=cmd).grid(row=r, column=2, **pad)

    def pick_src():
        p = filedialog.askopenfilename(title='Original ax3201p01.fmem1',
                                       filetypes=[('fmem1', '*.fmem1'), ('All', '*.*')])
        if p:
            src_v.set(p)
            if not dst_v.get():
                dst_v.set(os.path.join(os.path.dirname(p), 'kofxib', 'ax3201p01.fmem1'))

    def pick_dst():
        p = filedialog.asksaveasfilename(title='Output file', initialfile='ax3201p01.fmem1')
        if p:
            dst_v.set(p)

    row(0, 'Original ax3201p01.fmem1:', src_v, pick_src)
    row(1, 'Output (new file):', dst_v, pick_dst)
    status = tk.StringVar(value='Choose your own original ax3201p01.fmem1 (KOF XI), then press Patch.')
    ttk.Label(root, textvariable=status, wraplength=610).grid(row=2, column=0, columnspan=3, sticky='w', **pad)
    logbox = tk.Text(root, height=9, width=78, state='disabled')
    logbox.grid(row=3, column=0, columnspan=3, **pad)
    btn = ttk.Button(root, text='Patch')
    btn.grid(row=4, column=1, **pad)

    def log(t):
        def f():
            logbox.configure(state='normal')
            logbox.insert('end', t + '\n')
            logbox.see('end')
            logbox.configure(state='disabled')
            status.set(t)
        root.after(0, f)

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
                patch(s, d, log)
                root.after(0, lambda: messagebox.showinfo(TITLE, 'Finished. The patched file is ready:\n%s' % d))
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
    if len(argv) >= 3:      # CLI: aw_patcher SRC DST
        patch(argv[1], argv[2], print)
        return 0
    run_gui()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
