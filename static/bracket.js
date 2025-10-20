(function () {
  var configEl = document.getElementById('publicBracketConfig');
  var bracket = document.getElementById('tournamentBracket');
  if (!configEl || !bracket) {
    return;
  }

  var config = {};
  try {
    config = JSON.parse(configEl.textContent || configEl.innerText || '{}');
  } catch (err) {
    console.warn('Failed to parse bracket config', err);
    return;
  }

  var apiUrl = config.apiUrl;
  var intervalMs = parseInt(config.refreshInterval, 10);
  if (!apiUrl || !(intervalMs > 0)) {
    return;
  }

  var lastSeenUpdate = bracket.dataset ? bracket.dataset.updated : null;

  async function pollBracket() {
    try {
      var response = await fetch(apiUrl, { cache: 'no-cache' });
      if (!response.ok) {
        return;
      }
      var data = await response.json();
      if (!data || !data.meta) {
        return;
      }
      var updatedValue = data.meta.updated_at;
      if (updatedValue === null || updatedValue === undefined) {
        return;
      }
      var normalized = String(updatedValue);
      if (!lastSeenUpdate) {
        lastSeenUpdate = normalized;
        return;
      }
      if (normalized !== lastSeenUpdate) {
        window.location.reload();
      }
    } catch (err) {
      console.warn('Failed to refresh tournament bracket', err);
    }
  }

  setInterval(pollBracket, intervalMs);
})();
