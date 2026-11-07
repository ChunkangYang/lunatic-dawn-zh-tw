# .BMH 格式（Lunatic Dawn / Ld95.exe）

結論：.BMH = 「24-byte 檔頭 + 單一（或多個）靜態 Huffman 區塊」，解壓縮結果就是一份完整的 Windows DIB（BITMAPINFOHEADER 40 bytes + 調色盤 + 像素，無 BITMAPFILEHEADER）。
演算法：byte 為符號的 Huffman 編碼，**碼表以「每符號碼長 + 明確碼字位元」序列化**（不是 canonical 重建）。無 LZ、無 RLE。

逆向來源：Ld95_original.exe
- 0x407420：讀 0x18 bytes 檔頭 → 0x471430 檢查 byte[8]=='H' 且 byte[9]=='F' → 讀剩餘檔案 → 0x4716f0/0x471890 解壓
- 0x471450：解析區塊頭並建樹；0x4716f0 內迴圈 0x4717c0–0x471816：逐 bit 走樹輸出 byte
全部 518 個檔案以此解出，且 `解碼 → 重新編碼 → 再解碼` DIB 逐 byte 相同（bmh_encode.py --selftest）。

## 檔案配置（little-endian）

```
off 0x00  u32 file_size        = 檔案總長（所有檔案皆成立）
off 0x04  u32 dib_size         = 解壓後 DIB 總 bytes（= 40 + 4*調色盤色數 + stride*高）
off 0x08  u16 magic 0x4648     "HF"（bytes 48 46），後 2 bytes 為 00 00
off 0x0C  u32 = DIB[12:16]     planes(=1) | bitcount(=8)<<16 = 0x00080001；15 個檔為 0
off 0x10  u32 = DIB[16:20]     biCompression（=0）
off 0x14  u32 = DIB[20:24]     biSizeImage（=寬4對齊*高）；15 個檔為 0
off 0x18  block 0
          ...（若 dib_size 尚未湊滿則接下一個 block；所有現存檔案都只有 1 個 block）
```
0x0C–0x17 只是 DIB 檔頭欄位的拷貝，exe 讀進全域變數 (0xa9e3e8…) 後我們未見其影響解碼；
15 個檔（BA_KAZU、PLT_*、S_BACKG1-3、S_MESH、SROLL_01/16、S_nocopy、WP_LIGHT、s_backg0）這三欄為 0，照原值保留即可
（編碼器 `--like 原檔` 會複製，預設則從 DIB 檔頭取值）。

## Block 格式

```
u32 A      資料 bit 數（Huffman 資料部分的總 bit 數）；A==0 → 儲存區塊
u32 B      符號（byte）數；A==0 時為原始 bytes 數
-- A==0：後接 B 個原始 bytes，區塊結束（exe 以 memcpy 處理）
-- A!=0：
u8  len[256]        符號 0..255 各自碼長（0 = 未使用，範圍 0..16）
u8  codebits[ceil(sum(len)/8)]   依符號 0→255 順序，各符號的碼字，各佔 len[s] 個 bit，MSB first，緊密連續，末尾補 0 至 byte
u8  data[ceil(A/8)]              B 個符號的碼字連續，MSB first，末尾補 0
```
下一個 block 緊接在 data 之後（頭 = 0x108 + ceil(sum(len)/8) bytes）。

Bit 順序：每個 byte 由 bit7 往 bit0 讀（MSB first）。

### 解碼
建二元樹：對 s = 0..255、len[s]>0，從 codebits 讀 len[s] 個 bit 走樹（0=左,1=右），途中缺節點就新增，最後一個 bit 的子節點設為葉（符號 s）。
解資料：從根開始每讀 1 bit 往下，碰到葉就輸出該 byte 並回到根，直到輸出 B 個 byte。
（exe 的樹：兩個 0x200 項陣列，0x7fff=空，葉存 sym-256 為負值，內部節點存編號；碼必須是 prefix code，否則 exe 回傳錯誤。）

### 編碼（重新壓縮）
1. 統計 DIB 每個 byte 的出現次數，做 Huffman（單一符號時給 len=1）。碼長上限 16（原檔最大 16；超過時把頻率壓平重算）。
2. 碼字用 canonical 指派（依 (len, sym) 排序遞增）即可，因為碼字本身會被明確寫入檔案，exe 不要求特定指派方式。
3. 輸出 24-byte 檔頭 + `A=總bit數, B=len(DIB)` + len[256] + codebits + data。file_size 欄位填實際總長。
bmh_encode.py 即此實作；對 518 個檔解碼→編碼→再解碼 DIB 全部相同，總大小與原檔幾乎一致（20,838,600 vs 20,839,505 bytes）。
**未做**：未在實機（遊戲）載入驗證重新編碼的檔案（任務限制不改遊戲檔）；碼長上限 16 與 exe 陣列大小（512）相容，應無問題，但實機測試仍待做。

## DIB 內容
- BITMAPINFOHEADER 40 bytes（biSize=40）；調色盤固定 256 色 ×4 bytes（1024 bytes，BGRX）。那 15 個檔頭欄位為 0 的檔案 biClrUsed=256（其餘檔案的 biClrUsed 未逐一統計，解碼器 biClrUsed==0 時視為 256）。
- 全部 8bpp、biCompression=0、bottom-up（高度為正）、列 stride 4-byte 對齊。
- 調色盤位置：DIB offset 40，每色 4 bytes（B,G,R,0）。
- 沒有透明度欄位；黑色（索引 0）看來是遊戲內 color key。

## 其他
- 相關檔：.BMP 為標準 BMP，.TIL 未研究。
- 檔名：exe 的 .rsrc 字串表（UTF-16）存 `res\xxx.bmh` 路徑，載入時走 0x407a70（開檔 → 0x407420 讀檔頭/解壓）。
