"""
Playwright ile tarayıcı tabanlı transkript çekme – gerçek tarayıcı istekleri, engelden kaçınma.
"""
import asyncio
from typing import Optional, Tuple

from django.conf import settings


def _get_proxy_for_playwright() -> Optional[str]:
    """Settings'ten proxy URL (Playwright format: http://host:port veya socks5://...)."""
    single = getattr(settings, "YOUTUBE_PROXY", None) or None
    http_p = getattr(settings, "YOUTUBE_HTTP_PROXY", None) or None
    https_p = getattr(settings, "YOUTUBE_HTTPS_PROXY", None) or None
    if single:
        return single
    return https_p or http_p


async def _scrape_with_browser(video_id: str) -> Tuple[list, Optional[str]]:
    """Playwright ile sayfayı açıp transkripti DOM'dan alır."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return [], "playwright yüklü değil. Çalıştırın: pip install playwright && playwright install chromium"

    url = f"https://www.youtube.com/watch?v={video_id}"
    timeout_ms = getattr(settings, "TRANSCRIPT_BROWSER_TIMEOUT", 30000)
    proxy = _get_proxy_for_playwright()
    headless = getattr(settings, "TRANSCRIPT_BROWSER_HEADLESS", True)

    async with async_playwright() as p:
        launch_opts = {"headless": headless, "args": ["--disable-blink-features=AutomationControlled"]}
        if proxy:
            launch_opts["proxy"] = {"server": proxy}

        try:
            browser = await p.chromium.launch(**launch_opts)
        except Exception as e:
            return [], f"Tarayıcı başlatılamadı: {e}"

        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="tr-TR",
            )
            page = await context.new_page()

            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(2000)

            # Çerez uyarısı
            try:
                await page.evaluate("""() => {
                    const b = document.querySelector('button[aria-label*="cookies"], button[aria-label*="Çerez"], [aria-label*="Accept"], [aria-label*="Kabul"]');
                    if (b) b.click();
                }""")
                await page.wait_for_timeout(500)
            except Exception:
                pass

            # "Show transcript" / "Altyazıları göster" butonuna tıkla
            transcript_clicked = False
            selectors = [
                "ytd-video-description-transcript-section-renderer button",
                "button[aria-label*='transcript']",
                "button[aria-label*='Transcript']",
                "button[aria-label*='Altyazı']",
                "[data-target-id='engagement-panel-transcript'] button",
                "#transcript-button",
            ]
            for sel in selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        transcript_clicked = True
                        break
                except Exception:
                    continue
            if not transcript_clicked:
                await browser.close()
                return [], "Transkript butonu bulunamadı (video altyazı desteklemiyor olabilir)."

            await page.wait_for_timeout(2500)

            # Segmentleri al: #segments-container içindeki metin + varsa timestamp
            segments_data = await page.evaluate("""() => {
                const out = [];
                const container = document.querySelector('#segments-container');
                if (!container) return out;
                const segments = container.querySelectorAll('ytd-transcript-segment-renderer');
                if (segments.length) {
                    segments.forEach(el => {
                        const textEl = el.querySelector('yt-formatted-string.segment-text');
                        const timeEl = el.querySelector('span[aria-label]');
                        const text = textEl ? textEl.textContent.trim() : '';
                        let start = 0;
                        if (timeEl && timeEl.getAttribute('aria-label')) {
                            const m = timeEl.getAttribute('aria-label').match(/(\\d+):(\\d+)/);
                            if (m) start = parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
                        }
                        if (text) out.push({ text, start });
                    });
                }
                if (out.length === 0) {
                    const fallback = container.querySelectorAll('yt-formatted-string');
                    fallback.forEach((el, i) => {
                        const text = el.textContent.trim();
                        if (text) out.push({ text, start: i * 5 });
                    });
                }
                return out;
            }""")

            await browser.close()

            if not segments_data:
                return [], "Bu video için altyazı bulunamadı."

            # start/duration hesapla
            result = []
            for i, item in enumerate(segments_data):
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                start = float(item.get("start") or 0)
                next_start = segments_data[i + 1].get("start") if i + 1 < len(segments_data) else start + 5
                duration = max(0.1, next_start - start) if isinstance(next_start, (int, float)) else 5.0
                result.append({"text": text, "start": start, "duration": duration})

            return result, None

        except Exception as e:
            try:
                await browser.close()
            except Exception:
                pass
            return [], str(e)


def fetch_transcript_browser(video_id: str) -> Tuple[list, Optional[str]]:
    """
    Playwright ile tarayıcı açıp transkripti sayfadan çeker.
    Returns: (segments, error_message)
    """
    try:
        return asyncio.run(_scrape_with_browser(video_id))
    except Exception as e:
        return [], f"Tarayıcı transkript hatası: {e}"
