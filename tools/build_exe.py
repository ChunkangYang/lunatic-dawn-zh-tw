"""把 apply_patch.py 連同補丁資料打包成免安裝 Python 的 exe（PyInstaller --onedir），並輸出 zip。
用法： python -I tools/build_exe.py            （需 pip install pyinstaller；補丁來源 patch_tw/ 或 patch/）
輸出： dist/LunaticDawn-zh-TW-<版本>-tw-exe.zip
"""
import json, os, subprocess, sys, zipfile, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
pd = next((os.path.join(ROOT, d) for d in ('patch_tw', 'patch') if os.path.isfile(os.path.join(ROOT, d, 'manifest.json'))), None)
if not pd:
    sys.exit('找不到 patch_tw/ 或 patch/')
ver = json.load(open(os.path.join(pd, 'manifest.json'), encoding='utf-8'))['version']
work = os.path.join(ROOT, 'build_exe')
name = 'LunaticDawn-zh-TW-patcher'
subprocess.check_call([sys.executable, '-m', 'PyInstaller', '--onedir', '--console', '--noconfirm', '--name', name,
    '--distpath', os.path.join(work, 'dist'), '--workpath', os.path.join(work, 'work'), '--specpath', work,
    '--paths', HERE, '--add-data', pd + os.pathsep + 'patch', os.path.join(HERE, 'apply_patch.py')])
src = os.path.join(work, 'dist', name)
os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
z = os.path.join(ROOT, 'dist', 'LunaticDawn-zh-TW-%s-tw-exe.zip' % ver)
with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as f:
    for dp, dn, fn in os.walk(src):
        for n in fn:
            p = os.path.join(dp, n)
            f.write(p, os.path.join(name, os.path.relpath(p, src)))
print('exe zip：', z, os.path.getsize(z), 'sha256', hashlib.sha256(open(z, 'rb').read()).hexdigest())
