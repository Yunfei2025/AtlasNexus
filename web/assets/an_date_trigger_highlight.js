// Highlight the active "Open date" trigger button in the Summary > Books
// Alpha/Beta tables without forcing a server round-trip / table re-render.
// The Dash callback still owns which row is "active" (drives the calendar
// picker), but the visual highlight here is purely client-side.
(function () {
  function clearHighlights() {
    document.querySelectorAll('.an-date-trigger-btn.an-date-trigger-active').forEach(function (el) {
      el.classList.remove('an-date-trigger-active');
      el.style.background = 'rgba(99,179,237,0.08)';
    });
  }

  document.addEventListener('click', function (evt) {
    var btn = evt.target.closest('.an-date-trigger-btn');
    if (!btn) return;
    clearHighlights();
    btn.classList.add('an-date-trigger-active');
    btn.style.background = 'rgba(99,179,237,0.22)';
  });
})();
