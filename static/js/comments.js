/* 문제별 댓글 — lazy load + AJAX
 * - <details class="qcomments" data-qno="..."> 펼치면 첫 1회 로드.
 * - Premium members만 작성 가능. 그 외는 안내 + Premium 안내 링크.
 * - 답글은 1단계 (parent_id) 까지만.
 */
(function(){
  'use strict';

  function escapeHtml(s){ return String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function nl2br(s){ return escapeHtml(s).replace(/\r?\n/g, '<br>'); }
  function timeAgo(iso){
    if (!iso) return '';
    const d = new Date(iso); const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    if (diff < 86400*30) return Math.floor(diff/86400) + 'd ago';
    return d.toLocaleDateString('en-US');
  }

  function commentRowHtml(c, isReply){
    const adminBadge = c.is_admin ? '<span style="background:#fef3c7;color:#92400e;padding:1px 6px;border-radius:4px;font-size:0.72rem;font-weight:600;margin-left:4px;">Admin</span>' : '';
    const meBadge = c.is_mine ? '<span style="background:#dbeafe;color:#1e40af;padding:1px 6px;border-radius:4px;font-size:0.72rem;font-weight:600;margin-left:4px;">Me</span>' : '';
    const upvoteBtn = c.is_mine
        ? `<span style="color:var(--text-muted);font-size:0.8rem;">👍 ${c.upvotes}</span>`
        : `<button type="button" class="qc-vote" data-cid="${c.id}" style="background:${c.has_voted?'#dbeafe':'#fff'};border:1px solid ${c.has_voted?'#2563eb':'var(--border)'};border-radius:6px;padding:3px 9px;cursor:pointer;font-size:0.8rem;color:${c.has_voted?'#1e40af':'#374151'};">👍 ${c.upvotes}</button>`;
    const reportBtn = c.is_mine ? '' :
        `<button type="button" class="qc-report" data-cid="${c.id}" style="background:none;border:none;color:var(--text-muted);font-size:0.78rem;cursor:pointer;">Report</button>`;
    const deleteBtn = c.is_mine ?
        `<button type="button" class="qc-delete" data-cid="${c.id}" style="background:none;border:none;color:#dc2626;font-size:0.78rem;cursor:pointer;">Delete</button>` : '';
    const replyBtn = isReply ? '' :
        `<button type="button" class="qc-reply" data-cid="${c.id}" style="background:none;border:none;color:var(--primary);font-size:0.78rem;cursor:pointer;">Reply</button>`;
    return `
      <div class="qc-row" data-cid="${c.id}" style="padding:10px 0;border-bottom:1px solid #eef0f2;${isReply?'margin-left:24px;border-left:3px solid #e5e7eb;padding-left:12px;':''}">
        <div style="display:flex;align-items:center;gap:6px;font-size:0.78rem;color:var(--text-muted);margin-bottom:4px;">
          <strong style="color:#374151;">${escapeHtml(c.author_masked)}</strong>${adminBadge}${meBadge}
          <span>· ${timeAgo(c.created_at)}</span>
          ${c.edited_at ? '<span>· edited</span>' : ''}
        </div>
        <div style="font-size:0.92rem;line-height:1.55;color:#1f2937;white-space:pre-wrap;">${nl2br(c.body)}</div>
        <div style="display:flex;align-items:center;gap:10px;margin-top:6px;">
          ${upvoteBtn}
          ${replyBtn}
          ${reportBtn}
          ${deleteBtn}
        </div>
        <div class="qc-reply-form" data-parent="${c.id}"></div>
        <div class="qc-children"></div>
      </div>`;
  }

  function premiumGateHtml(){
    return `
      <div style="padding:14px;background:#fef9c3;border:1px solid #facc15;border-radius:8px;font-size:0.88rem;color:#854d0e;line-height:1.6;">
        💬 <strong>Premium members</strong> can read and join the discussion.<br>
        <a href="/upgrade" style="color:#1e40af;text-decoration:underline;font-weight:600;">→ Upgrade to Premium</a>
      </div>`;
  }

  function composerHtml(parentId){
    const cid = parentId ? `parent-${parentId}` : 'root';
    const placeholder = parentId ? 'Write a reply…' : 'Share your thoughts on this question. (Please avoid posting the answer directly.)';
    return `
      <form class="qc-composer" data-parent="${parentId||''}" style="margin-top:10px;">
        <textarea name="body" rows="${parentId?2:3}" maxlength="1500" placeholder="${placeholder}"
                  style="width:100%;border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:0.9rem;font-family:inherit;resize:vertical;"></textarea>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
          <span style="font-size:0.75rem;color:var(--text-muted);">Max 1500 chars · inappropriate posts will be reported/hidden</span>
          <div>
            ${parentId ? `<button type="button" class="qc-cancel-reply" style="background:none;border:none;color:var(--text-muted);font-size:0.85rem;cursor:pointer;">Cancel</button>` : ''}
            <button type="submit" style="background:#2563eb;color:#fff;border:none;border-radius:6px;padding:6px 14px;font-size:0.85rem;cursor:pointer;font-weight:600;">${parentId?'Post reply':'Post'}</button>
          </div>
        </div>
      </form>`;
  }

  function renderComments(box, data){
    const list = data.comments || [];
    if (data.premium_required) {
      box.innerHTML = premiumGateHtml();
      return;
    }
    // 트리 빌드: 부모-자식
    const byParent = {root: []};
    list.forEach(c => {
      const k = c.parent_id || 'root';
      (byParent[k] = byParent[k] || []).push(c);
    });
    const roots = byParent.root;
    let html = '';
    if (!roots.length) {
      html = '<div style="padding:12px 0;color:var(--text-muted);font-size:0.88rem;text-align:center;">No comments yet. Be the first to share!</div>';
    } else {
      roots.forEach(c => {
        html += commentRowHtml(c, false);
        const children = byParent[c.id] || [];
        // children은 별도 div에 — render 후 채워넣기 위해
      });
    }
    html += composerHtml(null);
    box.innerHTML = html;
    // 답글들 자식 영역에 배치
    roots.forEach(c => {
      const row = box.querySelector(`.qc-row[data-cid="${c.id}"] .qc-children`);
      if (!row) return;
      (byParent[c.id] || []).forEach(child => {
        row.insertAdjacentHTML('beforeend', commentRowHtml(child, true));
      });
    });
    bindActions(box);
  }

  function bindActions(box){
    const qno = box.closest('.qcomments').dataset.qno;
    // composer submit
    box.querySelectorAll('.qc-composer').forEach(form => {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const ta = form.querySelector('textarea');
        const body = (ta.value||'').trim();
        if (!body) return;
        const parentId = form.dataset.parent ? Number(form.dataset.parent) : null;
        try {
          const res = await fetch(`/api/comments/${qno}`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({body, parent_id: parentId})
          });
          const j = await res.json();
          if (!res.ok) { alert(j.error || 'Failed to post'); return; }
          ta.value = '';
          await reload(box);
        } catch (e) { alert('Network error'); }
      });
    });
    // upvote
    box.querySelectorAll('.qc-vote').forEach(btn => {
      btn.addEventListener('click', async () => {
        const cid = btn.dataset.cid;
        try {
          const res = await fetch(`/api/comments/${cid}/vote`, {method:'POST'});
          const j = await res.json();
          if (!res.ok) { alert(j.error || 'Failed'); return; }
          await reload(box);
        } catch (e) { alert('Network error'); }
      });
    });
    // delete
    box.querySelectorAll('.qc-delete').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to delete?')) return;
        const cid = btn.dataset.cid;
        try {
          const res = await fetch(`/api/comments/${cid}`, {method:'DELETE'});
          const j = await res.json();
          if (!res.ok) { alert(j.error || 'Failed'); return; }
          await reload(box);
        } catch (e) { alert('Network error'); }
      });
    });
    // report
    box.querySelectorAll('.qc-report').forEach(btn => {
      btn.addEventListener('click', async () => {
        const reason = prompt('Report reason (spam / offensive / spoiler / other):', 'spam');
        if (!reason) return;
        const cid = btn.dataset.cid;
        try {
          const res = await fetch(`/api/comments/${cid}/report`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({reason})
          });
          const j = await res.json();
          if (!res.ok) { alert(j.error || 'Failed'); return; }
          alert('Reported.');
        } catch (e) { alert('Network error'); }
      });
    });
    // reply form toggle
    box.querySelectorAll('.qc-reply').forEach(btn => {
      btn.addEventListener('click', () => {
        const cid = btn.dataset.cid;
        const replyBox = box.querySelector(`.qc-row[data-cid="${cid}"] > .qc-reply-form`);
        if (!replyBox) return;
        if (replyBox.innerHTML) { replyBox.innerHTML = ''; return; }
        replyBox.innerHTML = composerHtml(cid);
        bindActions(box); // 새 form 바인드
        replyBox.querySelector('textarea').focus();
        replyBox.querySelector('.qc-cancel-reply').addEventListener('click', () => {
          replyBox.innerHTML = '';
        });
      });
    });
  }

  async function reload(box){
    const qno = box.closest('.qcomments').dataset.qno;
    box.innerHTML = '<div style="color:var(--text-muted);font-size:0.85rem;">Loading…</div>';
    try {
      const res = await fetch(`/api/comments/${qno}`);
      const j = await res.json();
      renderComments(box, j);
      // 갯수 업데이트
      const countEl = box.closest('.qcomments').querySelector('.qcomments-count');
      if (countEl) countEl.textContent = j.total ? `${j.total}` : '';
    } catch(e) {
      box.innerHTML = '<div style="color:#dc2626;font-size:0.85rem;">Failed to load</div>';
    }
  }

  // details 펼침 시 lazy load
  document.addEventListener('toggle', (e) => {
    const det = e.target;
    if (!det.classList.contains('qcomments')) return;
    if (!det.open) return;
    const box = det.querySelector('.qcomments-body');
    if (box.dataset.loaded) return;
    box.dataset.loaded = '1';
    reload(box);
  }, true);
})();
