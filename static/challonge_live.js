(function () {
  const API_URL = '/api/challonge/tournament';
  const REFRESH_MS = 15000;

  const stateStrings = {
    complete: 'Final',
    underway: 'In Progress',
    pending: 'Upcoming',
    open: 'Upcoming'
  };

  function removeContent(section) {
    if (!section) return;
    while (section.children.length > 1) {
      section.removeChild(section.lastElementChild);
    }
  }

  function createMatchRow(match) {
    const li = document.createElement('li');
    li.className = 'match-row';
    if (match && match.id !== undefined && match.id !== null) {
      li.dataset.matchId = match.id;
    }

    const round = document.createElement('div');
    round.className = 'match-round';
    round.textContent = match?.round_label || 'Round';
    li.appendChild(round);

    const players = document.createElement('div');
    players.className = 'match-players';

    const player1 = document.createElement('span');
    player1.className = 'match-player';
    player1.textContent = match?.player1_name || 'TBD';
    if (match?.winner_slot === 'player1') {
      player1.classList.add('winner');
    }

    const vs = document.createElement('span');
    vs.className = 'match-vs';
    vs.textContent = 'vs';

    const player2 = document.createElement('span');
    player2.className = 'match-player';
    player2.textContent = match?.player2_name || 'TBD';
    if (match?.winner_slot === 'player2') {
      player2.classList.add('winner');
    }

    players.appendChild(player1);
    players.appendChild(vs);
    players.appendChild(player2);
    li.appendChild(players);

    const meta = document.createElement('div');
    meta.className = 'match-meta';
    if (match?.score_text) {
      const score = document.createElement('span');
      score.className = 'match-score';
      score.textContent = match.score_text;
      meta.appendChild(score);
    }
    const state = document.createElement('span');
    state.className = 'match-state';
    state.textContent = match?.status_text || '';
    meta.appendChild(state);
    li.appendChild(meta);
    return li;
  }

  function renderMatchList(section, matches, emptyText) {
    if (!section) return;
    removeContent(section);
    if (!matches || !matches.length) {
      const empty = document.createElement('p');
      empty.className = 'empty-copy';
      empty.textContent = emptyText;
      section.appendChild(empty);
      return;
    }
    const list = document.createElement('ul');
    list.className = 'match-list';
    matches.forEach((match) => {
      list.appendChild(createMatchRow(match));
    });
    section.appendChild(list);
  }

  function renderCurrent(section, match) {
    if (!section) return;
    removeContent(section);
    if (!match) {
      const empty = document.createElement('p');
      empty.className = 'empty-copy';
      empty.textContent = 'No live match right now.';
      section.appendChild(empty);
      return;
    }
    const card = document.createElement('div');
    card.className = 'current-match-card';
    if (match.id !== undefined && match.id !== null) {
      card.dataset.currentMatchId = match.id;
    }
    const round = document.createElement('div');
    round.className = 'match-round';
    round.textContent = match.round_label || 'Round';
    card.appendChild(round);

    const versus = document.createElement('div');
    versus.className = 'current-versus';

    const player1 = document.createElement('div');
    player1.className = 'current-player';
    player1.textContent = match.player1_name || 'TBD';
    if (match.winner_slot === 'player1') {
      player1.classList.add('winner');
    }

    const vs = document.createElement('div');
    vs.className = 'current-vs';
    vs.textContent = 'vs';

    const player2 = document.createElement('div');
    player2.className = 'current-player';
    player2.textContent = match.player2_name || 'TBD';
    if (match.winner_slot === 'player2') {
      player2.classList.add('winner');
    }

    versus.appendChild(player1);
    versus.appendChild(vs);
    versus.appendChild(player2);
    card.appendChild(versus);

    const meta = document.createElement('div');
    meta.className = 'current-meta';
    if (match.score_text) {
      const score = document.createElement('span');
      score.className = 'match-score';
      score.textContent = match.score_text;
      meta.appendChild(score);
    }
    const state = document.createElement('span');
    state.className = 'match-state';
    state.textContent = match.status_text || '';
    meta.appendChild(state);
    card.appendChild(meta);
    section.appendChild(card);
  }

  function renderRounds(section, rounds) {
    if (!section) return;
    removeContent(section);
    if (!rounds || !rounds.length) {
      const empty = document.createElement('p');
      empty.className = 'empty-copy';
      empty.textContent = 'Bracket data will appear once matches are seeded.';
      section.appendChild(empty);
      return;
    }
    const grid = document.createElement('div');
    grid.className = 'rounds-grid';
    rounds.forEach((round) => {
      const card = document.createElement('div');
      card.className = 'round-card';
      if (round.round !== undefined && round.round !== null) {
        card.dataset.round = round.round;
      }
      const title = document.createElement('h4');
      title.className = 'round-title';
      title.textContent = round.round_label || `Round ${round.round ?? ''}`;
      card.appendChild(title);

      const list = document.createElement('ul');
      list.className = 'match-list compact';
      (round.matches || []).forEach((match) => {
        list.appendChild(createMatchRow(match));
      });
      card.appendChild(list);
      grid.appendChild(card);
    });
    section.appendChild(grid);
  }

  function updateStatus(root, payload) {
    if (!root) return;
    const section = root.querySelector('[data-challonge-status]');
    if (!section) return;
    const tournament = payload?.tournament || null;
    const nameEl = section.querySelector('[data-challonge-name]');
    if (nameEl) {
      nameEl.textContent = tournament?.name || 'Challonge Tournament';
    }
    const stateEl = section.querySelector('[data-challonge-state]');
    if (stateEl) {
      if (tournament?.state) {
        const stateLabel = stateStrings[(tournament.state || '').toLowerCase()] || tournament.state;
        stateEl.textContent = '';
        const prefix = document.createTextNode('State: ');
        const highlight = document.createElement('span');
        highlight.className = 'highlight';
        highlight.textContent = stateLabel;
        stateEl.appendChild(prefix);
        stateEl.appendChild(highlight);
      } else {
        stateEl.textContent = 'Waiting for tournament details';
      }
    }
    const participantsEl = section.querySelector('[data-challonge-participants]');
    if (participantsEl) {
      participantsEl.textContent = tournament?.total_participants != null ? tournament.total_participants : '—';
    }
    const matchesEl = section.querySelector('[data-challonge-matches]');
    if (matchesEl) {
      matchesEl.textContent = tournament?.total_matches != null ? tournament.total_matches : '—';
    }
    const updatedEl = section.querySelector('[data-challonge-updated]');
    if (updatedEl) {
      updatedEl.textContent = payload?.fetched_at || '—';
    }
    const linkEl = section.querySelector('[data-challonge-link]');
    if (linkEl) {
      const url = tournament?.url;
      if (url) {
        linkEl.href = url;
        linkEl.removeAttribute('hidden');
      } else {
        linkEl.href = '#';
        linkEl.setAttribute('hidden', '');
      }
    }
    const errorEl = section.querySelector('[data-challonge-error]');
    if (errorEl) {
      const configured = payload?.configured !== false;
      const error = payload?.error;
      if (!configured) {
        errorEl.textContent = 'Challonge integration is not configured.';
        errorEl.removeAttribute('hidden');
      } else if (error) {
        errorEl.textContent = error;
        errorEl.removeAttribute('hidden');
      } else {
        errorEl.textContent = '';
        errorEl.setAttribute('hidden', '');
      }
    }
  }

  function applyPayload(root, payload) {
    if (!root) return;
    updateStatus(root, payload);
    const tournament = payload?.tournament || null;
    const currentSection = root.querySelector('[data-challonge-current]');
    renderCurrent(currentSection, tournament?.current_match || null);

    const upcomingSection = root.querySelector('[data-challonge-upcoming]');
    renderMatchList(
      upcomingSection,
      tournament?.upcoming_matches || [],
      'No upcoming matches have been posted.'
    );

    const recentSection = root.querySelector('[data-challonge-recent]');
    renderMatchList(
      recentSection,
      tournament?.recent_matches || [],
      'No matches have been completed yet.'
    );

    const roundsSection = root.querySelector('[data-challonge-rounds]');
    renderRounds(roundsSection, tournament?.rounds || []);
  }

  function fetchAndRender(root, scheduleNext) {
    fetch(API_URL, { cache: 'no-store' })
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          data = data || {};
          data.error = data.error || 'Unable to load tournament data.';
        }
        applyPayload(root, data);
        scheduleNext();
      })
      .catch((error) => {
        console.error('Challonge live update failed', error);
        applyPayload(root, {
          configured: true,
          error: 'Unable to load tournament data.',
          tournament: null,
        });
        scheduleNext();
      });
  }

  document.addEventListener('DOMContentLoaded', () => {
    const root = document.querySelector('[data-challonge-root]');
    if (!root) return;

    let timer = null;
    const scheduleNext = () => {
      if (timer) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => fetchAndRender(root, scheduleNext), REFRESH_MS);
    };

    fetchAndRender(root, scheduleNext);
  });
})();
