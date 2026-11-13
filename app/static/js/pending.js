// 待确认写入卡片（设计方案 §7.1 / 6.2，付佳宝名下）
// D1 只展示 args 原文；字段级 diff（before → after）等郑伟健的 before_json 接口到位后再补。
import { request } from '../request.js';

function toast(message) {
  const el = document.querySelector('#toast');
  el.textContent = message;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 2500);
}

// onConfirmed：某张卡片确认写入成功后刷新页面状态（统计条归 js/stats.js，由挂载方注入）
export function init({ onConfirmed } = {}) {
  const $ = s => document.querySelector(s);

  function render(rows) {
    $('#pending').innerHTML = (rows || [])
      .map(
        row => `<div class="pending"><strong>${row.tool}</strong> ${row.id}<pre>${JSON.stringify(
          row.args,
          null,
          2,
        )}</pre><button class="btn" data-id="${row.id}">确认写入</button></div>`,
      )
      .join('');

    $('#pending').querySelectorAll('[data-id]').forEach(button => {
      button.onclick = async () => {
        try {
          await request('/api/agent/confirm', {
            method: 'POST',
            body: { action_id: button.dataset.id },
          });
          toast('写入完成');
          $('#pending').innerHTML = '';
          if (onConfirmed) await onConfirmed();
        } catch (error) {
          toast(error.message);
        }
      };
    });
  }

  return { render };
}
