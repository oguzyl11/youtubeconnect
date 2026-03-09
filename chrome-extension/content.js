(function() {
  "use strict";

  var SITE_BASE_URL = "https://remapsoftware.net";

  function wait(ms) {
    return new Promise(function(r) { setTimeout(r, ms); });
  }

  async function getYouTubeTranscript() {
    // 1) Önce açıklama bölümündeki transkript butonunu dene (en yaygın)
    var descSection = document.querySelector("ytd-video-description-transcript-section-renderer");
    if (descSection) {
      var tbtn = descSection.querySelector("button");
      if (tbtn) {
        tbtn.click();
        await wait(1000);
      }
    }
    // 2) Engagement panel transkript butonu
    if (!document.querySelector("ytd-transcript-segment-renderer")) {
      var panelBtn = document.querySelector("[data-target-id='engagement-panel-transcript'] button");
      if (panelBtn) {
        panelBtn.click();
        await wait(1000);
      }
    }
    // 3) "More actions" (üç nokta) → "Show transcript"
    if (!document.querySelector("ytd-transcript-segment-renderer")) {
      var moreBtn = document.querySelector('button[aria-label="More actions"]') ||
                    document.querySelector('button[aria-label="Daha fazla işlem"]');
      if (moreBtn) {
        moreBtn.click();
        await wait(500);
        var labels = document.querySelectorAll("yt-formatted-string, span");
        for (var i = 0; i < labels.length; i++) {
          var t = (labels[i].textContent || "").trim();
          if (/show\s*transcript|transkript/i.test(t)) {
            labels[i].click();
            await wait(1000);
            break;
          }
        }
      }
    }

    // Panel açıldıktan sonra segmentleri oku
    var segments = document.querySelectorAll("ytd-transcript-segment-renderer");
    if (segments.length === 0) {
      segments = document.querySelectorAll("[class*='segment']");
    }
    var texts = [];
    for (var j = 0; j < segments.length; j++) {
      var segText = segments[j].querySelector(".segment-text") ||
                    segments[j].querySelector("[class*='segment-text']") ||
                    segments[j];
      if (segText && segText.textContent) {
        texts.push(segText.textContent.trim());
      }
    }
    return texts.join("\n");
  }

  function showPanel() {
    if (document.getElementById("yt-remap-transcript-panel")) return;
    var panel = document.createElement("div");
    panel.id = "yt-remap-transcript-panel";
    panel.innerHTML =
      "<h4>Transkript</h4>" +
      "<button class=\"btn-get\" type=\"button\">Transkripti al (DOM)</button>" +
      "<button class=\"btn-send\" type=\"button\" disabled>Siteye gönder</button>" +
      "<p class=\"status\" id=\"yt-remap-status\"></p>";
    document.body.appendChild(panel);

    var statusEl = panel.querySelector(".status");
    var sendBtn = panel.querySelector(".btn-send");
    var lastTranscript = "";
    var videoUrl = window.location.href.split("?")[0] + "?v=" + (new URLSearchParams(window.location.search).get("v") || "");

    panel.querySelector(".btn-get").addEventListener("click", function() {
      statusEl.textContent = "Alınıyor...";
      sendBtn.disabled = true;
      getYouTubeTranscript()
        .then(function(text) {
          lastTranscript = text;
          if (text) {
            sendBtn.disabled = false;
            statusEl.textContent = text.split("\n").length + " parça alındı.";
          } else {
            statusEl.textContent = "Transkript bulunamadı. Önce videoda \"...\" → \"Show transcript\" açın.";
          }
        })
        .catch(function(err) {
          statusEl.textContent = "Hata: " + (err.message || err);
        });
    });

    sendBtn.addEventListener("click", function() {
      if (!lastTranscript) {
        statusEl.textContent = "Önce \"Transkripti al\" ile alın.";
        return;
      }
      chrome.runtime.sendMessage({
        action: "openSiteWithTranscript",
        transcript: lastTranscript,
        url: videoUrl
      }, function() {
        statusEl.textContent = "Site açıldı; transkript gönderildi.";
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", showPanel);
  } else {
    showPanel();
  }
})();
