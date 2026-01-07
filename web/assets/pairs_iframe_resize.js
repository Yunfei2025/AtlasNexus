// Auto-resize the PAIRS iframe to match its content height (same-origin only)
(function () {
  function getDocHeight(doc) {
    if (!doc) return null;
    try {
      const body = doc.body;
      const html = doc.documentElement;
      if (!body || !html) return null;
      return Math.max(
        body.scrollHeight,
        html.scrollHeight,
        body.offsetHeight,
        html.offsetHeight,
        body.clientHeight,
        html.clientHeight
      );
    } catch (e) {
      return null;
    }
  }

  function resizePairsIframe() {
    var iframe = document.getElementById('pairs-iframe');
    if (!iframe) return;
    try {
      var doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
      var h = getDocHeight(doc);
      if (h && !isNaN(h)) {
        // Clamp to sensible min/max
        var minH = 600;
        var maxH = 3000; // adjust as needed
        var newH = Math.max(minH, Math.min(maxH, h + 10));
        iframe.style.height = newH + 'px';
      }
    } catch (e) {
      // Cross-origin or timing errors are ignored
    }
  }

  function schedule() {
    // Initial attempt after DOM is ready
    resizePairsIframe();
    // Try again shortly after load for late style/layout
    setTimeout(resizePairsIframe, 300);
    setTimeout(resizePairsIframe, 800);
    // Periodic adjustments in case content changes
    var intervalMs = 1500;
    var attempts = 0;
    var maxAttempts = 40; // ~60s of adjustments
    var iv = setInterval(function () {
      attempts += 1;
      resizePairsIframe();
      if (attempts >= maxAttempts) {
        clearInterval(iv);
      }
    }, intervalMs);

    // Also try on window resize
    window.addEventListener('resize', resizePairsIframe);

    // When iframe completes loading a new document, adjust again
    var iframe = document.getElementById('pairs-iframe');
    if (iframe) {
      iframe.addEventListener('load', function () {
        // Slight delay to let content settle
        setTimeout(resizePairsIframe, 100);
        setTimeout(resizePairsIframe, 400);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedule);
  } else {
    schedule();
  }
})();
