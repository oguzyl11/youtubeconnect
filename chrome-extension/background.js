"use strict";

var SITE_BASE_URL = "https://remapsoftware.net";

function openSiteWithTranscript(transcript, url) {
  var targetUrl = SITE_BASE_URL.replace(/\/$/, "") + "/transcript/";
  chrome.tabs.create({ url: targetUrl }, function(tab) {
    function listener(tabId, info) {
      if (tabId !== tab.id || info.status !== "complete") return;
      chrome.tabs.onUpdated.removeListener(listener);
      chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: function(transcript, url) {
          window.postMessage({ type: "FROM_EXTENSION", transcript: transcript, url: url }, "*");
        },
        args: [transcript, url]
      }).catch(function() {});
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {
  if (msg.action === "openSiteWithTranscript" && msg.transcript != null) {
    openSiteWithTranscript(msg.transcript, msg.url || "");
    sendResponse();
  }
  return true;
});
