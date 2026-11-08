"""俠客遊：前途道標（Lunatic Dawn: Passage of the Book，Steam 版）繁體中文補丁安裝程式。

用法：
  python apply_patch.py                      自動尋找 Steam 版遊戲資料夾並安裝
  python apply_patch.py --game "D:\\...\\LunaticDawnPotB"
  python apply_patch.py --check              只檢查，不改檔
  python apply_patch.py --restore            還原成原版（使用安裝時留下的 .orig 備份）
  （開發用）--patch-dir <資料夾>               指定補丁資料夾（例如 patch_tw）
tw 版（0.2.x，Big5）需把 Windows 系統地區設為「中文（台灣）」；jp 版（0.1.x）需設為「日文（日本）」。

補丁只含「差異位元組」，不含遊戲本身的內容；你必須擁有正版遊戲。安裝時會把被修改的檔案先備份成
<檔名>.orig，再套用補丁，並用 SHA-256 檢查結果。Steam「驗證遊戲檔案完整性」會把檔案還原成日文版，
屆時重新執行本程式即可。
"""
import json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))
from patchlib import sha256, apply_diff, bmh_to_payload, dib_to_bmh_like  # noqa: E402

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

GAME_DIR = 'LunaticDawnPotB'


def find_patch_dir():
    # 發布包內一律放在 patch/；開發樹內 tw 版在 patch_tw/（用 --patch-dir 指定）
    if '--patch-dir' in sys.argv:
        d = sys.argv[sys.argv.index('--patch-dir') + 1]
        if os.path.isfile(os.path.join(d, 'manifest.json')):
            return d
        sys.exit('找不到 %s\\manifest.json' % d)
    for d in (os.path.join(HERE, 'patch'), os.path.join(os.path.dirname(HERE), 'patch')):
        if os.path.isfile(os.path.join(d, 'manifest.json')):
            return d
    sys.exit('找不到 patch\\manifest.json，請確認補丁資料夾完整。')


def steam_libraries():
    cands = []
    for pf in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), r'C:\Program Files (x86)'):
        if pf:
            cands.append(os.path.join(pf, 'Steam'))
    libs = []
    for s in cands:
        vdf = os.path.join(s, 'steamapps', 'libraryfolders.vdf')
        libs.append(s)
        if os.path.isfile(vdf):
            try:
                txt = open(vdf, encoding='utf-8', errors='replace').read()
                for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                    libs.append(m.group(1).replace('\\\\', '\\'))
            except OSError:
                pass
    seen, out = set(), []
    for l in libs:
        if l.lower() not in seen:
            seen.add(l.lower()); out.append(l)
    return out


def find_game():
    for lib in steam_libraries():
        p = os.path.join(lib, 'steamapps', 'common', GAME_DIR)
        if os.path.isfile(os.path.join(p, 'Ld95.exe')):
            return p
    return None


def locate(game, rel):
    """在遊戲資料夾內找檔案（不分大小寫）。"""
    cur = game
    for part in rel.replace('\\', '/').split('/'):
        if not os.path.isdir(cur):
            return None
        hit = next((n for n in os.listdir(cur) if n.lower() == part.lower()), None)
        if hit is None:
            return None
        cur = os.path.join(cur, hit)
    return cur


def build_new(entry, data, patch_dir):
    diff = open(os.path.join(patch_dir, entry['diff']), 'rb').read()
    if entry['kind'] == 'bmh':
        _, dib = bmh_to_payload(data)
        return dib_to_bmh_like(apply_diff(dib, diff), data)
    return apply_diff(data, diff)


def main():
    args = sys.argv[1:]
    if '-h' in args or '--help' in args:
        print(__doc__); return 0
    game = args[args.index('--game') + 1] if '--game' in args else find_game()
    if not game or not os.path.isfile(os.path.join(game, 'Ld95.exe')):
        print('找不到遊戲資料夾。請用 --game "<路徑>" 指定（資料夾內要有 Ld95.exe）。')
        return 2
    patch_dir = find_patch_dir()
    manifest = json.load(open(os.path.join(patch_dir, 'manifest.json'), encoding='utf-8'))
    check, restore = '--check' in args, '--restore' in args
    print('遊戲資料夾：', game)
    print('補丁版本：', manifest['version'])

    profile = manifest.get('profile', 'jp')
    need_acp = manifest.get('required_acp', 932)
    print('版本類型：', 'tw（Big5，需系統地區「中文（台灣）」）' if need_acp == 950 else 'jp（CP932，需系統地區「日文（日本）」）')

    if sys.platform == 'win32' and not restore:
        try:
            import ctypes
            acp = ctypes.windll.kernel32.GetACP()
            if acp != need_acp:
                want = '中文（台灣）' if need_acp == 950 else '日文（日本）'
                print('\n提醒：你的 Windows「非 Unicode 程式使用的語言」碼頁是 %d，本補丁（%s 版）需要 %d。'
                      '遊戲內文字是 CP%d 編碼，要正確顯示必須把系統地區設成「%s」並重新開機'
                      '（設定 → 時間與語言 → 語言與區域 → 管理語言設定 → 變更系統地區設定）。'
                      '不建議用 Locale Emulator（進入世界後可能閃退）。\n' % (acp, profile, need_acp, need_acp, want))
        except Exception:
            pass

    ok = patched = skipped = failed = 0
    for e in manifest['files']:
        path = locate(game, e['path'])
        if path is None:
            print('找不到：', e['path']); failed += 1; continue
        bak = path + '.orig'
        if restore:
            if os.path.isfile(bak):
                shutil.copy2(bak, path); print('已還原：', e['path']); ok += 1
            else:
                print('沒有備份，略過：', e['path']); skipped += 1
            continue
        data = open(path, 'rb').read()
        h = sha256(data)
        if h == e['new_sha256']:
            print('已是中文版：', e['path']); skipped += 1; continue
        if h != e['orig_sha256']:
            print('檔案不是支援的原版（版本不同或已被其他方式修改）：', e['path'])
            failed += 1; continue
        try:
            new = build_new(e, data, patch_dir)
        except Exception as ex:
            print('套用失敗：', e['path'], ex); failed += 1; continue
        if sha256(new) != e['new_sha256']:
            print('結果雜湊不符，已放棄：', e['path']); failed += 1; continue
        if check:
            print('可套用：', e['path']); ok += 1; continue
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'wb') as f:
            f.write(new)
        print('已套用：', e['path']); patched += 1
    label = '還原' if restore else ('可套用' if check else '套用')
    print('\n完成：%s %d、略過 %d、失敗 %d' % (label, patched + ok, skipped, failed))
    if failed:
        print('有檔案失敗。常見原因：遊戲版本與補丁不符，請在 Steam 驗證遊戲檔案完整性後重試。')
        return 1
    return 0


if __name__ == '__main__':
    try:
        rc = main()
    except SystemExit as ex:
        rc = ex.code
        if isinstance(rc, str):
            print(rc); rc = 1
    if getattr(sys, 'frozen', False) and len(sys.argv) == 1:  # exe 雙擊執行時，結束前暫停讓使用者看結果
        try:
            input('\n按 Enter 結束...')
        except EOFError:
            pass
    sys.exit(rc)
