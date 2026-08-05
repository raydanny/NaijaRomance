// ── Nav Toggle (Mobile) ───────────────────────────────────────────────────────
const navToggle = document.getElementById('navToggle');
const navLinks  = document.getElementById('navLinks');
if (navToggle && navLinks) {
  navToggle.addEventListener('click', () => navLinks.classList.toggle('open'));
}

// ── Profile Dropdown ──────────────────────────────────────────────────────────
const profileDrop = document.getElementById('profileDrop');
const profileMenu = document.getElementById('profileMenu');
if (profileDrop && profileMenu) {
  profileDrop.addEventListener('click', e => {
    e.stopPropagation();
    profileMenu.classList.toggle('open');
    if (notifDropdown) notifDropdown.classList.remove('open');
  });
}

// ── Notification Bell Dropdown ────────────────────────────────────────────────
const notifBell     = document.getElementById('notifBell');
const notifDropdown = document.getElementById('notifDropdown');
const notifDropBody = document.getElementById('notifDropBody');
const notifBadge    = document.getElementById('notifBadge');
let notifLoaded = false;

function loadNotifications() {
  fetch('/notifications/json')
    .then(r => r.json())
    .then(data => {
      // Update badge
      if (notifBadge) {
        if (data.count > 0) { notifBadge.textContent = data.count; notifBadge.style.display='flex'; }
        else                 { notifBadge.style.display = 'none'; }
      }
      if (!notifDropBody) return;
      if (data.items.length === 0) {
        notifDropBody.innerHTML = '<div class="notif-empty">No new notifications</div>';
        return;
      }
      notifDropBody.innerHTML = data.items.map(n => `
        <a href="${n.link}" class="notif-drop-item">
          <span class="nd-text">${n.text}</span>
          <span class="nd-time">${n.time}</span>
        </a>`).join('');
      notifLoaded = true;
    })
    .catch(() => {});
}

if (notifBell && notifDropdown) {
  notifBell.addEventListener('click', e => {
    e.stopPropagation();
    const isOpen = notifDropdown.classList.toggle('open');
    if (profileMenu) profileMenu.classList.remove('open');
    if (isOpen && !notifLoaded) loadNotifications();
  });
  // Poll every 30 seconds
  setInterval(() => { loadNotifications(); notifLoaded = false; }, 30000);
}

// Close all dropdowns on outside click
document.addEventListener('click', () => {
  if (profileMenu)  profileMenu.classList.remove('open');
  if (notifDropdown) notifDropdown.classList.remove('open');
});

// ── Auto-dismiss Flash Alerts ─────────────────────────────────────────────────
document.querySelectorAll('.alert').forEach(el => {
  setTimeout(() => {
    el.style.transition = 'opacity .4s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 400);
  }, 5000);
});

// ── Toast helper ──────────────────────────────────────────────────────────────
function showToast(msg, color) {
  const t = document.createElement('div');
  t.className = 'toast';
  if (color) t.style.background = color;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => {
    t.style.transition = 'opacity .4s';
    t.style.opacity = '0';
    setTimeout(() => t.remove(), 400);
  }, 3500);
}

// ── Like Buttons ──────────────────────────────────────────────────────────────
document.querySelectorAll('.like-btn').forEach(btn => {
  btn.addEventListener('click', function(e) {
    e.preventDefault(); e.stopPropagation();
    const uid = this.dataset.uid;
    fetch(`/like/${uid}`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.status === 'liked') {
          this.classList.add('liked');
          if (data.mutual) showToast('💚 It\'s a mutual match!');
          else             showToast('❤️ Profile liked!');
        } else if (data.status === 'unliked') {
          this.classList.remove('liked');
        }
      })
      .catch(() => {});
  });
});

// ── Strength Bar Animated Fill ────────────────────────────────────────────────
document.querySelectorAll('.strength-bar-fill').forEach(bar => {
  const target = bar.style.width;
  bar.style.width = '0';
  setTimeout(() => { bar.style.width = target; }, 200);
});

// ── Browse Sort Tabs ──────────────────────────────────────────────────────────
// Only applies to <button> sort tabs that have a data-sort attribute (browse page).
// <a> sort tabs (online filter, report status tabs) are plain links — skip them.
document.querySelectorAll('button.sort-tab[data-sort]').forEach(tab => {
  tab.addEventListener('click', function() {
    const url = new URL(window.location.href);
    url.searchParams.set('sort', this.dataset.sort);
    url.searchParams.set('page', '1');
    window.location.href = url.toString();
  });
});

// ── Back to Top ───────────────────────────────────────────────────────────────
const bttBtn = document.getElementById('backToTop');
if (bttBtn) {
  window.addEventListener('scroll', () => {
    bttBtn.classList.toggle('btt-visible', window.scrollY > 400);
  });
  bttBtn.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
}

// ── AJAX Unread Count Polling (every 15 seconds) ──────────────────────────────
(function startUnreadPolling() {
  // Only run when the user is authenticated
  if (document.body.dataset.authed !== 'true') return;

  function pollUnread() {
    fetch('/api/unread-counts')
      .then(r => r.json())
      .then(data => {
        // Update message badge in desktop nav
        document.querySelectorAll('.nav-msg-badge').forEach(el => {
          el.textContent  = data.messages;
          el.style.display = data.messages > 0 ? 'flex' : 'none';
        });
        // Update bottom nav message badge
        document.querySelectorAll('.bnav-badge').forEach(el => {
          el.textContent   = data.messages;
          el.style.display = data.messages > 0 ? 'inline-block' : 'none';
        });
        // Update notification badge count
        if (notifBadge) {
          notifBadge.textContent   = data.notifications;
          notifBadge.style.display = data.notifications > 0 ? 'flex' : 'none';
          notifLoaded = false; // allow re-load on next bell click
        }
        // Update wink badge in nav dropdown
        document.querySelectorAll('.nav-wink-badge').forEach(el => {
          el.textContent   = data.winks;
          el.style.display = data.winks > 0 ? 'inline-block' : 'none';
        });
        // Update page title indicator
        const totalUnread = data.messages + data.notifications;
        if (totalUnread > 0) {
          document.title = document.title.replace(/^\(\d+\) /, '');
          document.title = `(${totalUnread}) ` + document.title;
        } else {
          document.title = document.title.replace(/^\(\d+\) /, '');
        }
      })
      .catch(() => {});
  }

  pollUnread();                          // immediate call on page load
  setInterval(pollUnread, 15000);
})();

// ── Live Online Count Badge ───────────────────────────────────────────────────
(function pollOnlineCount() {
  const badge = document.getElementById('onlineNavCount');
  if (!badge) return;
  function update() {
    fetch('/api/online-count')
      .then(r => r.json())
      .then(data => {
        if (data.count > 0) {
          badge.textContent  = data.count;
          badge.style.display = 'inline-flex';
        } else {
          badge.style.display = 'none';
        }
      })
      .catch(() => {});
  }
  update();
  setInterval(update, 30000);
})();

// ── Skeleton Screen Reveal ────────────────────────────────────────────────────
// Once the page is fully loaded, remove skeleton classes
window.addEventListener('load', () => {
  document.querySelectorAll('.skeleton').forEach(el => {
    el.classList.remove('skeleton');
  });
});

// ── Global Wink Button Handler ────────────────────────────────────────────────
// Handles .wink-send-btn on any page (browse, matches, online, profile)
// The profile page and conversation page also have their own handlers;
// this global one fires only when those local handlers are absent.
document.addEventListener('click', function(e) {
  const btn = e.target.closest('.wink-send-btn');
  if (!btn) return;
  // Skip if this button already has a specific click listener attached
  // (profile.html and conversation.html define their own)
  if (btn.dataset.winkHandled) return;
  e.preventDefault(); e.stopPropagation();
  const uid = btn.dataset.uid;
  if (!uid) return;
  btn.dataset.winkHandled = '1';   // mark so we don't double-fire
  fetch(`/wink/${uid}`, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      showToast(d.message || '😉 Wink sent!');
      btn.disabled = true;
      btn.style.opacity = '0.6';
    })
    .catch(() => showToast('Could not send wink.', '#e74c3c'));
});

// ── Password Show/Hide Toggle ─────────────────────────────────────────────────
// Defined globally so inline onclick="togglePw('id')" calls work from any template.
function togglePw(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const btn = el.closest('.input-eye')?.querySelector('.eye-btn i');
  if (el.type === 'password') {
    el.type = 'text';
    if (btn) { btn.classList.remove('fa-eye'); btn.classList.add('fa-eye-slash'); }
  } else {
    el.type = 'password';
    if (btn) { btn.classList.remove('fa-eye-slash'); btn.classList.add('fa-eye'); }
  }
}

// ── Confirm-before-submit for dangerous forms ─────────────────────────────────
// Any form with data-confirm attribute shows a confirm dialog before submitting.
document.addEventListener('submit', function(e) {
  const form = e.target;
  const msg  = form.dataset.confirm;
  if (msg && !confirm(msg)) {
    e.preventDefault();
  }
});

// ── Auto-focus first input on auth pages ─────────────────────────────────────
(function() {
  const authCard = document.querySelector('.auth-card input:not([type=hidden])');
  if (authCard && !authCard.value) authCard.focus();
})();

// ── Smooth anchor links ───────────────────────────────────────────────────────
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', function(e) {
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

// ── Search form: clear button ─────────────────────────────────────────────────
// Adds a live × button inside any .search-input-large when it has a value.
(function() {
  const input = document.querySelector('.search-input-large');
  if (!input) return;
  const wrap = input.closest('.search-input-wrap');
  if (!wrap) return;

  const clearBtn = document.createElement('button');
  clearBtn.type = 'button';
  clearBtn.className = 'search-clear-btn';
  clearBtn.innerHTML = '<i class="fas fa-times"></i>';
  clearBtn.title = 'Clear search';
  clearBtn.style.cssText = [
    'position:absolute', 'right:120px', 'top:50%', 'transform:translateY(-50%)',
    'background:none', 'border:none', 'color:#b2bec3', 'font-size:.85rem',
    'cursor:pointer', 'padding:4px 8px', 'transition:color .15s',
    'display:none'
  ].join(';');
  clearBtn.addEventListener('mouseenter', () => clearBtn.style.color = '#636e72');
  clearBtn.addEventListener('mouseleave', () => clearBtn.style.color = '#b2bec3');

  wrap.style.position = 'relative';
  wrap.appendChild(clearBtn);

  function updateClear() {
    clearBtn.style.display = input.value ? 'block' : 'none';
  }
  input.addEventListener('input', updateClear);
  updateClear();

  clearBtn.addEventListener('click', () => {
    input.value = '';
    input.focus();
    updateClear();
  });
})();
