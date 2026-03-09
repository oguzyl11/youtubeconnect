# YouTube Transcript – Chrome Extension

YouTube watch sayfasında transkripti **DOM üzerinden** okur (YouTube’un kendi “Show transcript” paneli). Bu yöntem sunucu tarafında engellenmez.

## Kurulum

1. Chrome’da `chrome://extensions/` açın.
2. “Geliştirici modu”nu açın.
3. “Paketlenmemiş öğe yükle” ile bu klasörü seçin (`chrome-extension`).

## Kullanım

1. Bir YouTube video sayfasına gidin (`youtube.com/watch?v=...`).
2. Sağ altta **Transkript** paneli görünür.
3. **Transkripti al (DOM)** ile sayfadaki transkript panelini açıp metni okutun (gerekirse videoda “…” → “Show transcript” ile paneli açın).
4. **Siteye gönder** ile transkript, yapılandırdığınız sitedeki transkript sayfasına gönderilir ve orada görüntülenir.

## Site adresi (localhost / farklı domain)

Varsayılan adres: `https://remapsoftware.net`

Yerelde denemek veya farklı bir site kullanmak için aynı adresi hem **content.js** hem **background.js** içinde güncelleyin:

- `content.js`: en üstte `var SITE_BASE_URL = "https://remapsoftware.net";`
- `background.js`: en üstte `var SITE_BASE_URL = "https://remapsoftware.net";`

Örnek: `http://localhost:8000` kullanacaksanız her iki dosyada bu değeri yazın.

## Gereksinimler

- Transkript sayfası (`/transcript/`) `postMessage` ile `type: 'FROM_EXTENSION'` ve `transcript`, `url` alanlarını dinlemeli (bu projedeki şablon buna göre ayarlı).
- Backend `POST /api/transcript/` isteğinde opsiyonel `transcript` alanını kabul etmeli (bu projede mevcut).
