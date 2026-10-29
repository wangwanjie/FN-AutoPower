/* AutoPower 主页脚本：三语切换、三态主题、24 小时计划环、下载直链、滚动渐入 */
(function () {
  'use strict';

  var doc = document.documentElement;
  doc.classList.add('js');
  var REPO = 'wangwanjie/FN-AutoPower';
  var reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');

  /* ---------- 文案 ---------- */
  // zh-CN 文案直接取自 HTML，这里只放额外的运行时文案与其他两种语言
  var I18N = {
    'zh-CN': {
      title: 'AutoPower 自动开关机 · 飞牛 fnOS 定时开机、关机与重启',
      desc: 'AutoPower 是飞牛 fnOS 应用，为 NAS 设置定时开机、定时关机和定时重启计划。定时开机通过主板 RTC 唤醒实现，纯 Python + Bash，MIT 开源。',
      ogDesc: '飞牛 fnOS 定时开机、关机与重启：RTC 唤醒，纯 Python + Bash，MIT 开源。',
      days: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
      stOn: '运行中', stOff: '已关机',
      act: { on: '开机', off: '关机', reboot: '重启' },
      notes: { r1: '工作日上班前开机', r2: '工作日夜间关机', r3: '周末晚点开机', r4: '周末熬夜后关机', r5: '每周一凌晨重启' },
      next: '下一项：{t} {a} · {n}', nextTomorrow: '下一项：明天 {t} {a} · {n}', none: '本日没有计划',
      cmd: 'sudo python3 -I /var/apps/autopower/target/AutoPower/src/autopower_executor.py --install <数据目录>',
      copied: '已复制'
    },
    en: {
      title: 'AutoPower · Scheduled power on, shutdown and reboot for fnOS NAS',
      desc: 'AutoPower is an fnOS app that schedules power on, shutdown and reboot for your NAS. Power on uses motherboard RTC wake. Pure Python + Bash, MIT licensed.',
      ogDesc: 'Scheduled power on, shutdown and reboot for fnOS: RTC wake, pure Python + Bash, MIT licensed.',
      days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
      stOn: 'Running', stOff: 'Powered off',
      act: { on: 'Power on', off: 'Shutdown', reboot: 'Reboot' },
      notes: { r1: 'On before the workday', r2: 'Off on weeknights', r3: 'Later start on weekends', r4: 'Off after a late weekend night', r5: 'Early Monday reboot' },
      next: 'Next: {t} {a} · {n}', nextTomorrow: 'Next: tomorrow {t} {a} · {n}', none: 'No schedules on this day',
      cmd: 'sudo python3 -I /var/apps/autopower/target/AutoPower/src/autopower_executor.py --install <data-dir>',
      copied: 'Copied',
      skip: 'Skip to content', brandAria: 'AutoPower home', iconAlt: 'AutoPower icon', brandSub: '',
      navAria: 'Page navigation', navFeatures: 'Features', navScreens: 'Screenshots', navHow: 'How it works', navInstall: 'Install', navChangelog: 'Changelog',
      langAria: 'Language', themeAria: 'Theme', themeLight: 'Light', themeDark: 'Dark', themeSystem: 'Follow system', ghAria: 'GitHub repository',
      eyebrow: 'fnOS app · MIT open source',
      h1a: 'Let your NAS keep', h1b: 'a day–night rhythm',
      lead: 'Schedule power on, shutdown and reboot for your NAS: boot automatically on weekday mornings, shut down late at night, and use a different timetable on weekends. Power on is done through motherboard RTC wake; shutdown and reboot run from a system scheduled task.',
      dlX86: 'Download x86', dlArm: 'Download ARM', dlNote: 'Not sure? Run', dlSums: 'SHA256 checksums',
      chip1: 'Pure Python + Bash', chip2: 'x86 · ARM', chip3: 'No internet access',
      daysAria: 'Preview weekday', ringAria: '24-hour schedule ring, use arrow keys to change the preview time',
      lgOn: 'Power on', lgOff: 'Shutdown', lgReboot: 'Reboot', lgHint: 'Drag the hand to preview a sample schedule',
      fTitle: 'One schedule list for power on, shutdown and reboot',
      f1t: 'Three actions', f1d: 'Add, edit, delete, enable or disable power on, shutdown and reboot schedules, each with an optional note.',
      f2t: 'Flexible days', f2d: 'Every day, weekdays (Mon–Fri), weekends (Sat, Sun) or specific days of the week.',
      f3t: 'Next 7 days', f3d: 'The home page shows the next run time and a preview of the next 7 days.',
      f4t: 'Conflict warnings', f4d: 'Warns when different actions share a time, such as power on and shutdown, or shutdown and reboot, and when schedules repeat.',
      f5t: 'RTC wake', f5d: 'Before any shutdown, including a manual one, the next power-on time is written to the motherboard RTC.',
      f6t: 'Clock offset compensation', f6d: 'Wakes correctly whether the motherboard clock runs on UTC or local time: the executor measures the RTC offset and compensates.',
      f7t: 'Status at a glance', f7d: 'Shows executor status, the RTC alarm time and recent shutdown and reboot records.',
      sTitle: 'Interface',
      sMainAlt: 'AutoPower main screen: schedule list and 7-day preview', sMainCap: 'Main screen: schedule list, next run time and 7-day preview',
      sEditAlt: 'Edit schedule dialog', sEditCap: 'Edit a schedule',
      sDeployAlt: 'Executor deployment dialog: status, RTC alarm and deploy command', sDeployCap: 'Executor deployment: status, RTC alarm and recent runs',
      hTitle: 'The app plans, the executor acts',
      hSub: 'The app runs without privileges and only edits schedules. Shutdown, reboot and writing the RTC alarm need root, so a separate executor does them after an administrator deploys it once.',
      n1t: 'AutoPower app', n1d: 'Runs as the package user, listens only on 127.0.0.1:3868, reached through fnOS login',
      n2t: 'Schedule file', n2d: 'The executor validates each entry against a whitelist, rejects symlinks and limits the size',
      n3t: 'Root executor', n3d: 'cron runs it every minute: on a match it calls /sbin/poweroff or /sbin/reboot and syncs the RTC wake alarm',
      sec1: 'The executor only shuts down, reboots and writes the RTC, and never runs commands from configuration',
      sec2: 'Write APIs accept only application/json, blocking cross-site form posts; request bodies are limited to 64KB',
      sec3: 'Works on LAN and over the internet with no extra ports or reverse proxy',
      sec4: 'No internet access and no data collection',
      iTitle: 'Four steps to install',
      i1t: 'Download the package', i1d: 'Pick x86 for Intel / AMD processors and ARM for ARM processors. Run uname -m over SSH: x86_64 means x86, aarch64 means ARM. x86 is verified on real hardware; ARM is not yet.',
      i2t: 'Manual install', i2d: 'Upload the package in fnOS App Center → Manual install.',
      i3t: 'Deploy the executor', i3d: 'Open the app, click Executor deployment, copy the command and run it once over SSH as an administrator. Use the command shown in the app, since the data directory depends on the install volume.',
      copy: 'Copy',
      i4t: 'Enable RTC wake', i4d: 'Turn on RTC wake in BIOS/UEFI (called Resume by RTC Alarm, Wake on RTC and so on). Scheduled shutdown and reboot work without it.',
      iNote: 'If the app says the executor is outdated after an upgrade, run the deploy command again. Before uninstalling the app, copy the uninstall command from Executor deployment and run it.',
      cTitle: 'Recent updates',
      c142: 'Redrawn icon: the power symbol is centered, the 64 px icon is drawn on the pixel grid, and the shape matches fnOS system icons. Executor unchanged.',
      c141: 'Fixed dialogs being cut off on short windows, the list scrolling behind open dialogs on phones, and the weekday menu covering the Reboot option.',
      c140: 'Added scheduled reboot; warns when different actions share a time; fixed fresh install failure (error 10237). Executor 1.2.0 requires redeployment.',
      c130: 'Separate x86 and ARM packages with SHA-256 checksums; schedule notes, 7-day preview and conflict warnings; all times shown in the NAS time zone, correct across DST.',
      cMore: 'Full changelog →',
      footAria: 'Footer links', more: 'More by VanJay', repo: 'GitHub repository', issues: 'Feedback', license: 'MIT License'
    },
    'zh-TW': {
      title: 'AutoPower 自動開關機 · 飛牛 fnOS 定時開機、關機與重新啟動',
      desc: 'AutoPower 是飛牛 fnOS 應用程式，為 NAS 設定定時開機、定時關機與定時重新啟動排程。定時開機透過主機板 RTC 喚醒實現，純 Python + Bash，MIT 開源。',
      ogDesc: '飛牛 fnOS 定時開機、關機與重新啟動：RTC 喚醒，純 Python + Bash，MIT 開源。',
      days: ['週一', '週二', '週三', '週四', '週五', '週六', '週日'],
      stOn: '運作中', stOff: '已關機',
      act: { on: '開機', off: '關機', reboot: '重新啟動' },
      notes: { r1: '工作日上班前開機', r2: '工作日夜間關機', r3: '週末晚點開機', r4: '週末熬夜後關機', r5: '每週一凌晨重新啟動' },
      next: '下一項：{t} {a} · {n}', nextTomorrow: '下一項：明天 {t} {a} · {n}', none: '本日沒有排程',
      cmd: 'sudo python3 -I /var/apps/autopower/target/AutoPower/src/autopower_executor.py --install <資料目錄>',
      copied: '已複製',
      skip: '跳到正文', brandAria: 'AutoPower 首頁', iconAlt: 'AutoPower 圖示', brandSub: '自動開關機',
      navAria: '頁面導覽', navFeatures: '功能', navScreens: '截圖', navHow: '原理', navInstall: '安裝', navChangelog: '更新',
      langAria: '語言', themeAria: '主題', themeLight: '淺色', themeDark: '深色', themeSystem: '跟隨系統', ghAria: 'GitHub 儲存庫',
      eyebrow: '飛牛 fnOS 應用程式 · MIT 開源',
      h1a: '讓 NAS 跟著', h1b: '晝夜作息',
      lead: '為 NAS 設定定時開機、定時關機與定時重新啟動：工作日早上自動開機、深夜自動關機，週末按另一套時間執行。定時開機透過主機板 RTC 喚醒實現，關機與重新啟動由系統排程任務執行。',
      dlX86: '下載 x86 版', dlArm: '下載 ARM 版', dlNote: '不確定架構時 SSH 執行', dlSums: 'SHA256 校驗檔案',
      chip1: '純 Python + Bash', chip2: 'x86 · ARM', chip3: '不存取外部網路',
      daysAria: '預覽星期', ringAria: '24 小時排程環，用方向鍵調整預覽時間',
      lgOn: '開機', lgOff: '關機', lgReboot: '重新啟動', lgHint: '拖曳指針預覽範例排程',
      fTitle: '一張排程表，管好開機、關機與重新啟動',
      f1t: '三種操作', f1d: '新增、編輯、刪除、啟用、停用開機、關機或重新啟動排程，每條排程可加上備註。',
      f2t: '彈性的日期', f2d: '每天、平日（週一至週五）、假日（週六、週日）或指定星期。',
      f3t: '未來 7 天預覽', f3d: '首頁顯示下一次執行時間，以及未來 7 天的執行預覽。',
      f4t: '衝突提示', f4d: '同一時間既開機又關機、既關機又重新啟動，或排程重複時給出提示。',
      f5t: 'RTC 喚醒', f5d: '關機（包括手動關機）前自動把下一次開機時間寫入主機板 RTC。',
      f6t: '時鐘偏差自動補償', f6d: '主機板時鐘走 UTC 或本地時間都能正確喚醒：執行器測量 RTC 與系統時間的偏差並自動補償。',
      f7t: '狀態一目了然', f7d: '介面顯示執行器運作狀態、RTC 鬧鐘時間與最近的關機、重新啟動紀錄。',
      sTitle: '介面',
      sMainAlt: 'AutoPower 主畫面：排程清單與未來 7 天預覽', sMainCap: '主畫面：排程清單、下次執行時間與未來 7 天預覽',
      sEditAlt: '編輯排程視窗', sEditCap: '編輯排程',
      sDeployAlt: '執行器部署視窗：運作狀態、RTC 鬧鐘與部署指令', sDeployCap: '執行器部署：狀態、RTC 鬧鐘與最近執行紀錄',
      hTitle: '應用程式負責排程，執行器負責動手',
      hSub: '應用程式以一般權限執行，只編輯排程。關機、重新啟動與寫入主機板 RTC 鬧鐘需要 root，由管理員部署一次的獨立執行器完成。',
      n1t: 'AutoPower 應用程式', n1d: '以套件使用者執行，只監聽 127.0.0.1:3868，經飛牛登入驗證存取',
      n2t: '排程檔案', n2d: '執行器依白名單逐條校驗，拒絕符號連結並限制大小',
      n3t: 'root 執行器', n3d: 'cron 每分鐘執行一次：命中排程時呼叫 /sbin/poweroff 或 /sbin/reboot，並同步 RTC 喚醒鬧鐘',
      sec1: '執行器只做關機、重新啟動與寫入 RTC 三件事，不執行任何來自設定的指令',
      sec2: '寫入介面只接受 application/json，阻擋跨站表單提交；請求內容限制 64KB',
      sec3: '內網與公網存取都不需要額外連接埠或反向代理',
      sec4: '不存取外部網路，不收集任何資料',
      iTitle: '四步裝好',
      i1t: '下載安裝套件', i1d: 'Intel / AMD 處理器選 x86 版，ARM 處理器選 ARM 版。SSH 執行 uname -m：輸出 x86_64 選 x86，輸出 aarch64 選 ARM。x86 已實機驗證，ARM 尚未實機驗證。',
      i2t: '手動安裝', i2d: '在飛牛「應用中心 → 手動安裝」上傳安裝套件。',
      i3t: '部署執行器', i3d: '開啟應用程式，點「執行器部署」，複製部署指令，用管理員帳號 SSH 登入 NAS 執行一次。實際指令以應用程式內顯示的為準（資料目錄因安裝磁碟區而異）。',
      copy: '複製',
      i4t: '開啟 RTC 喚醒', i4d: '在 BIOS/UEFI 中開啟 RTC 喚醒（不同主機板稱為 Resume by RTC Alarm、Wake on RTC 等）。定時關機與重新啟動不依賴這一步。',
      iNote: '應用程式升級後介面提示「執行器版本過舊」時，重新執行一次部署指令即可。解除安裝應用程式前，先在「執行器部署」中複製解除安裝指令執行。',
      cTitle: '最近更新',
      c142: '重繪應用程式圖示：電源符號置中，64 像素圖示依像素網格繪製，外形與飛牛系統圖示一致。執行器無變化。',
      c141: '修正視窗高度不足時彈出視窗底部被遮住、手機上彈出視窗開啟時帶動清單捲動、星期下拉選單蓋住「重新啟動」選項。',
      c140: '新增定時重新啟動；同一時間存在不同操作時給出衝突提示；修正全新安裝失敗（錯誤碼 10237）。執行器升級到 1.2.0，需要重新部署。',
      c130: '分 x86 與 ARM 兩個安裝套件並附 SHA-256 校驗；新增排程備註、未來 7 天預覽與衝突提示；時間統一依 NAS 系統時區顯示，跨日光節約時間也正確。',
      cMore: '完整更新日誌 →',
      footAria: '頁尾連結', more: 'VanJay 的更多作品', repo: 'GitHub 儲存庫', issues: '回報問題', license: 'MIT 授權條款'
    }
  };

  // 把 HTML 中的简体文案收集为 zh-CN 词典，切回简体时使用
  var zh = I18N['zh-CN'];
  document.querySelectorAll('[data-i18n]').forEach(function (el) {
    zh[el.dataset.i18n] = el.textContent;
  });
  document.querySelectorAll('[data-i18n-aria]').forEach(function (el) {
    zh[el.dataset.i18nAria] = el.getAttribute('aria-label');
  });
  document.querySelectorAll('[data-i18n-alt]').forEach(function (el) {
    zh[el.dataset.i18nAlt] = el.getAttribute('alt');
  });

  function pickLang() {
    var q = window.__apLang;
    if (q && I18N[q]) {
      return q;
    }
    try {
      var saved = localStorage.getItem('ap-lang');
      if (saved && I18N[saved]) {
        return saved;
      }
    } catch (e) {}
    var list = navigator.languages || [navigator.language || 'en'];
    for (var i = 0; i < list.length; i++) {
      var l = String(list[i]).toLowerCase();
      if (/^zh-(tw|hk|mo|hant)/.test(l)) {
        return 'zh-TW';
      }
      if (l.indexOf('zh') === 0) {
        return 'zh-CN';
      }
      if (l.indexOf('en') === 0) {
        return 'en';
      }
    }
    return 'en';
  }

  var lang = pickLang();
  function T() {
    return I18N[lang];
  }

  function applyLang(next, save) {
    lang = next;
    var d = T();
    doc.lang = lang;
    document.title = d.title;
    document.querySelector('meta[name="description"]').setAttribute('content', d.desc);
    document.querySelector('meta[property="og:title"]').setAttribute('content', d.title);
    document.querySelector('meta[property="og:description"]').setAttribute('content', d.ogDesc);
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var v = d[el.dataset.i18n];
      if (v != null) {
        el.textContent = v;
      }
    });
    document.querySelectorAll('[data-i18n-aria]').forEach(function (el) {
      var v = d[el.dataset.i18nAria];
      if (v != null) {
        el.setAttribute('aria-label', v);
      }
    });
    document.querySelectorAll('[data-i18n-alt]').forEach(function (el) {
      var v = d[el.dataset.i18nAlt];
      if (v != null) {
        el.setAttribute('alt', v);
      }
    });
    document.getElementById('cmd').textContent = d.cmd;
    document.querySelectorAll('#langSeg button').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.lang === lang));
    });
    if (save) {
      try {
        localStorage.setItem('ap-lang', lang);
      } catch (e) {}
    }
    buildDays();
    render();
  }

  /* ---------- 主题 ---------- */
  var darkMQ = matchMedia('(prefers-color-scheme: dark)');
  function applyTheme(pref, save) {
    var dark = pref === 'dark' || (pref === 'system' && darkMQ.matches);
    doc.dataset.theme = dark ? 'dark' : 'light';
    doc.dataset.themePref = pref;
    document.querySelector('meta[name="theme-color"]').setAttribute('content', dark ? '#0a0d22' : '#f3faf4');
    document.querySelectorAll('#themeSeg button').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.themeSet === pref));
    });
    if (save) {
      try {
        localStorage.setItem('ap-theme', pref);
      } catch (e) {}
    }
  }
  darkMQ.addEventListener('change', function () {
    if (doc.dataset.themePref === 'system') {
      applyTheme('system', false);
    }
  });
  document.getElementById('themeSeg').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (b) {
      applyTheme(b.dataset.themeSet, true);
    }
  });
  document.getElementById('langSeg').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (b) {
      applyLang(b.dataset.lang, true);
    }
  });

  /* ---------- 24 小时计划环 ---------- */
  // 示例计划与 README 截图中的演示数据一致；星期 1=周一 … 7=周日
  var RULES = [
    { id: 'r1', days: [1, 2, 3, 4, 5], m: 8 * 60 + 30, a: 'on' },
    { id: 'r2', days: [1, 2, 3, 4, 5], m: 23 * 60, a: 'off' },
    { id: 'r3', days: [6, 7], m: 10 * 60, a: 'on' },
    { id: 'r4', days: [6, 7], m: 60 + 30, a: 'off' },
    { id: 'r5', days: [1], m: 4 * 60, a: 'reboot' }
  ];
  var SVGNS = 'http://www.w3.org/2000/svg';
  var R = 150;
  var ring = document.getElementById('ring');
  var nas = document.getElementById('nas');
  var sun = document.getElementById('sun');
  var moon = document.getElementById('moon');
  var hand = document.getElementById('hand');
  var skyNight = document.getElementById('skyNight');
  var rtTime = document.getElementById('rtTime');
  var rtState = document.getElementById('rtState');
  var rtNext = document.getElementById('rtNext');
  var daysBox = document.getElementById('days');

  var now = new Date();
  var day = ((now.getDay() + 6) % 7) + 1;
  var minute = now.getHours() * 60 + now.getMinutes();
  var events = [];
  var startOn = false;
  // 验收用参数：?t=08:30 固定预览时间（并暂停自动播放），?day=1..7 指定星期
  var qs = new URLSearchParams(location.search);
  var qt = /^(\d{1,2}):?(\d{2})$/.exec(qs.get('t') || '');
  if (qt) {
    minute = (Number(qt[1]) % 24) * 60 + Math.min(59, Number(qt[2]));
  }
  if (/^[1-7]$/.test(qs.get('day') || '')) {
    day = Number(qs.get('day'));
  }

  function el(name, attrs) {
    var n = document.createElementNS(SVGNS, name);
    for (var k in attrs) {
      n.setAttribute(k, attrs[k]);
    }
    return n;
  }
  // 分钟数 → 环上坐标：0 点在底部，12 点在顶部，顺时针
  function pt(m, r) {
    var a = m / 1440 * Math.PI * 2;
    return [-Math.sin(a) * r, Math.cos(a) * r];
  }
  function fmt(m) {
    m = ((Math.round(m) % 1440) + 1440) % 1440;
    var h = Math.floor(m / 60), mm = m % 60;
    return (h < 10 ? '0' : '') + h + ':' + (mm < 10 ? '0' : '') + mm;
  }
  function eventsOf(d) {
    return RULES.filter(function (r) {
      return r.days.indexOf(d) >= 0;
    }).sort(function (a, b) {
      return a.m - b.m;
    });
  }
  // 当天 0 点的开关机状态：往前找最近一条开机/关机事件
  function stateAtStart(d) {
    for (var k = 1; k <= 7; k++) {
      var pd = ((d - k - 1 + 7) % 7) + 1;
      var ev = eventsOf(pd).filter(function (e) {
        return e.a !== 'reboot';
      });
      if (ev.length) {
        return ev[ev.length - 1].a === 'on';
      }
    }
    return false;
  }
  function stateAt(m) {
    var s = startOn;
    events.forEach(function (e) {
      if (e.m <= m && e.a !== 'reboot') {
        s = e.a === 'on';
      }
    });
    return s;
  }
  function arcPath(m1, m2) {
    var p1 = pt(m1, R), p2 = pt(m2, R);
    var large = (m2 - m1) > 720 ? 1 : 0;
    return 'M' + p1[0].toFixed(2) + ' ' + p1[1].toFixed(2) + 'A' + R + ' ' + R + ' 0 ' + large + ' 1 ' + p2[0].toFixed(2) + ' ' + p2[1].toFixed(2);
  }

  function buildTicks() {
    var g = document.getElementById('ticks');
    for (var h = 0; h < 24; h++) {
      var major = h % 6 === 0;
      var a = pt(h * 60, major ? 118 : 124), b = pt(h * 60, 131);
      g.appendChild(el('line', { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: 'tick' + (major ? ' tick-major' : '') }));
      if (major) {
        var c = pt(h * 60, 104);
        var t = el('text', { x: c[0], y: c[1], class: 'tick-label' });
        t.textContent = h === 0 ? '0' : String(h);
        g.appendChild(t);
      }
    }
  }

  function buildDay() {
    events = eventsOf(day);
    startOn = stateAtStart(day);
    var arcs = document.getElementById('arcs');
    var marks = document.getElementById('marks');
    arcs.textContent = '';
    marks.textContent = '';
    // 按开机/关机事件把一天切成若干段，开机段绿色，关机段靛蓝
    var cuts = [0];
    events.forEach(function (e) {
      if (e.a !== 'reboot') {
        cuts.push(e.m);
      }
    });
    cuts.push(1440);
    for (var i = 0; i < cuts.length - 1; i++) {
      var a = cuts[i], b = cuts[i + 1];
      if (b - a < 1) {
        continue;
      }
      var on = stateAt(a);
      if (b - a >= 1439.9) {
        arcs.appendChild(el('circle', { r: R, class: on ? 'arc-on' : 'arc-off' }));
      } else {
        arcs.appendChild(el('path', { d: arcPath(a, b), class: on ? 'arc-on' : 'arc-off' }));
      }
    }
    events.forEach(function (e) {
      var p = pt(e.m, R), q = pt(e.m, 82);
      var g = el('g', { class: 'mark mark-' + (e.a === 'reboot' ? 'rb' : e.a) });
      g.appendChild(el('circle', { cx: p[0], cy: p[1], r: 7 }));
      var t = el('text', { x: q[0], y: q[1] });
      t.textContent = fmt(e.m);
      g.appendChild(t);
      marks.appendChild(g);
    });
  }

  function buildDays() {
    daysBox.textContent = '';
    T().days.forEach(function (name, i) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(i + 1 === day));
      b.textContent = name;
      b.addEventListener('click', function () {
        day = i + 1;
        buildDays();
        buildDay();
        render();
      });
      daysBox.appendChild(b);
    });
  }

  var lastOn = null;
  function render() {
    var m = minute;
    var ang = m / 1440 * 360;
    hand.setAttribute('transform', 'rotate(' + ang.toFixed(2) + ')');
    sun.setAttribute('transform', 'rotate(' + ang.toFixed(2) + ')');
    moon.setAttribute('transform', 'rotate(' + (ang + 180).toFixed(2) + ')');
    // 白天程度：12 点为 1，0 点为 0，用于太阳、月亮与夜空的透明度
    var dayness = (1 - Math.cos(m / 1440 * Math.PI * 2)) / 2;
    sun.style.opacity = Math.min(1, Math.max(.15, dayness * 1.6)).toFixed(2);
    moon.style.opacity = Math.min(1, Math.max(.15, (1 - dayness) * 1.6)).toFixed(2);
    skyNight.style.opacity = Math.max(0, 1 - dayness * 1.8).toFixed(2);

    var on = stateAt(m);
    if (on !== lastOn) {
      nas.classList.toggle('on', on);
      lastOn = on;
    }
    var d = T();
    rtTime.textContent = fmt(m);
    rtState.textContent = on ? d.stOn : d.stOff;
    rtState.className = 'rt-state ' + (on ? 'on' : 'off');

    var nx = null, tomorrow = false;
    for (var i = 0; i < events.length; i++) {
      if (events[i].m > m) {
        nx = events[i];
        break;
      }
    }
    if (!nx) {
      var tm = eventsOf(day % 7 + 1);
      if (tm.length) {
        nx = tm[0];
        tomorrow = true;
      }
    }
    rtNext.textContent = nx ? (tomorrow ? d.nextTomorrow : d.next).replace('{t}', fmt(nx.m)).replace('{a}', d.act[nx.a]).replace('{n}', d.notes[nx.id]) : d.none;
    ring.setAttribute('aria-valuenow', String(Math.round(m)));
    ring.setAttribute('aria-valuetext', fmt(m) + ' ' + (on ? d.stOn : d.stOff));
  }

  // 自动播放：一天约 24 秒走完；经过重启时间点时让 NAS 闪一下
  var playing = !reduceMotion.matches && !qt;
  var visible = true, inView = true, raf = 0, lastTs = 0, resumeTimer = 0;
  function tick(ts) {
    raf = 0;
    if (!playing || !visible || !inView) {
      return;
    }
    if (lastTs) {
      var prev = minute;
      minute += (ts - lastTs) / 1000 * 60;
      if (minute >= 1440) {
        minute -= 1440;
        day = day % 7 + 1;
        buildDays();
        buildDay();
      }
      events.forEach(function (e) {
        if (e.a === 'reboot' && prev < e.m && minute >= e.m) {
          flashReboot();
        }
      });
    }
    lastTs = ts;
    render();
    raf = requestAnimationFrame(tick);
  }
  function startLoop() {
    if (!raf && playing && visible && inView) {
      lastTs = 0;
      raf = requestAnimationFrame(tick);
    }
  }
  function flashReboot() {
    nas.classList.remove('reboot');
    void nas.getBBox();
    nas.classList.add('reboot');
  }
  function pauseForUser() {
    playing = false;
    clearTimeout(resumeTimer);
    if (!reduceMotion.matches) {
      resumeTimer = setTimeout(function () {
        playing = true;
        startLoop();
      }, 6000);
    }
  }

  // 拖动指针：按指针相对环心的角度换算时间，吸附到 5 分钟
  var hit = document.getElementById('hit');
  var dragging = false;
  function setFromPointer(e) {
    var r = ring.getBoundingClientRect();
    var x = e.clientX - (r.left + r.width / 2);
    var y = e.clientY - (r.top + r.height / 2);
    var a = Math.atan2(-x, y);
    if (a < 0) {
      a += Math.PI * 2;
    }
    var m = Math.round(a / (Math.PI * 2) * 1440 / 5) * 5;
    var before = minute;
    minute = m % 1440;
    events.forEach(function (ev) {
      if (ev.a === 'reboot' && Math.abs(before - ev.m) < 60 && ((before < ev.m && minute >= ev.m) || (before > ev.m && minute <= ev.m))) {
        flashReboot();
      }
    });
    render();
  }
  hit.addEventListener('pointerdown', function (e) {
    dragging = true;
    pauseForUser();
    ring.classList.add('dragging');
    try {
      hit.setPointerCapture(e.pointerId);
    } catch (err) {}
    setFromPointer(e);
    e.preventDefault();
  });
  hit.addEventListener('pointermove', function (e) {
    if (dragging) {
      setFromPointer(e);
    }
  });
  function endDrag() {
    if (dragging) {
      dragging = false;
      ring.classList.remove('dragging');
      pauseForUser();
    }
  }
  hit.addEventListener('pointerup', endDrag);
  hit.addEventListener('pointercancel', endDrag);
  ring.addEventListener('keydown', function (e) {
    var step = e.shiftKey ? 60 : 15;
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      minute = (Math.floor(minute / step) * step + step) % 1440;
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      minute = (Math.ceil(minute / step) * step - step + 1440) % 1440;
    } else if (e.key === 'Home') {
      minute = 0;
    } else if (e.key === 'End') {
      minute = 1435;
    } else {
      return;
    }
    e.preventDefault();
    pauseForUser();
    render();
  });

  document.addEventListener('visibilitychange', function () {
    visible = !document.hidden;
    startLoop();
  });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (list) {
      inView = list[0].isIntersecting;
      startLoop();
    }).observe(ring);
  }
  reduceMotion.addEventListener('change', function () {
    playing = !reduceMotion.matches;
    startLoop();
  });

  /* ---------- 复制命令 ---------- */
  document.querySelectorAll('.copy').forEach(function (b) {
    b.addEventListener('click', function () {
      var text = document.getElementById(b.dataset.copy).textContent;
      var done = function () {
        b.textContent = T().copied;
        setTimeout(function () {
          b.textContent = T().copy;
        }, 1600);
      };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(done, function () {});
      }
    });
  });

  /* ---------- 滚动渐入 ---------- */
  var reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !reduceMotion.matches) {
    var io = new IntersectionObserver(function (list) {
      list.forEach(function (en) {
        if (en.isIntersecting) {
          en.target.classList.add('in');
          io.unobserve(en.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px' });
    reveals.forEach(function (r) {
      io.observe(r);
    });
  } else {
    reveals.forEach(function (r) {
      r.classList.add('in');
    });
  }

  /* ---------- 下载直链：用 Release API 把按钮换成最新 fpk 直链，失败时保留 releases/latest ---------- */
  var CACHE_KEY = 'ap-release';
  function applyRelease(info) {
    if (info.x86) {
      document.getElementById('dlX86').href = info.x86;
    }
    if (info.arm) {
      document.getElementById('dlArm').href = info.arm;
    }
    if (info.sums) {
      document.getElementById('dlSums').href = info.sums;
    }
    if (info.tag) {
      document.getElementById('verLabel').textContent = info.tag;
    }
  }
  function loadRelease() {
    // 缓存 1 小时，避免匿名 API 频率限制
    try {
      var cached = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
      if (cached && Date.now() - cached.at < 3600 * 1000) {
        applyRelease(cached);
        return;
      }
    } catch (e) {}
    if (!window.fetch) {
      return;
    }
    fetch('https://api.github.com/repos/' + REPO + '/releases/latest', { headers: { Accept: 'application/vnd.github+json' } })
      .then(function (r) {
        if (!r.ok) {
          throw new Error(r.status);
        }
        return r.json();
      })
      .then(function (rel) {
        var assets = rel.assets || [];
        function find(re) {
          for (var i = 0; i < assets.length; i++) {
            if (re.test(assets[i].name)) {
              return assets[i].browser_download_url;
            }
          }
          return null;
        }
        var info = { x86: find(/-x86\.fpk$/i), arm: find(/-arm\.fpk$/i), sums: find(/SHA256SUMS\.txt$/i), tag: rel.tag_name, at: Date.now() };
        applyRelease(info);
        try {
          localStorage.setItem(CACHE_KEY, JSON.stringify(info));
        } catch (e) {}
      })
      .catch(function () {});
  }

  /* ---------- 初始化 ---------- */
  applyTheme(doc.dataset.themePref || 'system', false);
  buildTicks();
  buildDay();
  applyLang(lang, false);
  startLoop();
  loadRelease();
})();
