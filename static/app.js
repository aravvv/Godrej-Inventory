// Godrej Inventory Automation Client Application (Modern AI Workspace UI)
const App = {
  state: {
    currentUser: null,
    currentMode: "IN", // 'IN', 'OUT', 'CAME_IN_AND_WENT_OUT'
    currentMethod: "SLIP", // 'SLIP', 'BILL'
    stagedBatch: [],
    inventoryData: [],
    empPageSize: 60,
    empVisibleCount: 60,
    adminPageSize: 100,
    adminVisibleCount: 100,
    searchDebounceTimer: null,
    adminSearchDebounceTimer: null,
    theme: "dark",
    audioCtx: null
  },

  init() {
    this.initTheme();
    this.bindEvents();
    this.checkSession();
  },

  initTheme() {
    const saved = localStorage.getItem("godrej_theme") || "dark";
    this.applyTheme(saved);
  },

  toggleTheme() {
    const next = this.state.theme === "dark" ? "light" : "dark";
    localStorage.setItem("godrej_theme", next);
    this.applyTheme(next);
  },

  applyTheme(theme) {
    this.state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    const icon = document.getElementById("themeIcon");
    const label = document.getElementById("themeLabel");
    if (icon && label) {
      if (theme === "dark") {
        icon.textContent = "☀️";
        label.textContent = "Light";
      } else {
        icon.textContent = "🌙";
        label.textContent = "Dark";
      }
    }
  },

  inlineLoaderHtml(msg = "Syncing...") {
    return `<span class="ai-inline-loader"><span class="ai-pulse-dots"><span></span><span></span><span></span></span><span>${msg}</span></span>`;
  },

  // Audio & Haptic Feedback for Warehouse
  playSuccessSound() {
    try {
      if (!this.state.audioCtx) {
        this.state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      const ctx = this.state.audioCtx;
      if (ctx.state === 'suspended') ctx.resume();

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1760, ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.15);
    } catch (e) {}

    if (navigator.vibrate) {
      navigator.vibrate([60, 40, 60]);
    }
  },

  showToast(message, type = "info") {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.className = `toast toast-${type}`;
    toast.classList.remove("hidden");
    setTimeout(() => {
      toast.classList.add("hidden");
    }, 3500);
  },

  bindEvents() {
    document.getElementById("loginForm").addEventListener("submit", (e) => {
      e.preventDefault();
      this.handleLogin();
    });

    document.getElementById("logoutBtn").addEventListener("click", () => {
      this.handleLogout();
    });
  },

  checkSession() {
    const saved = localStorage.getItem("godrej_user");
    if (saved) {
      try {
        this.state.currentUser = JSON.parse(saved);
        this.updateUserHeader();
        this.showScreen("employeeScreen");
        this.refreshFromSheets(null, true);
      } catch (e) {
        localStorage.removeItem("godrej_user");
        this.showScreen("loginScreen");
      }
    } else {
      this.showScreen("loginScreen");
    }
  },

  showScreen(screenId) {
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    const target = document.getElementById(screenId);
    if (target) {
      target.classList.add("active");
    }

    if (screenId === "adminScreen") {
      this.loadInventory(true);
      this.loadAuditLogs();
      this.loadUsers();
      this.loadBackups();
      this.loadSettings();
    } else if (screenId === "employeeInventoryScreen") {
      this.loadInventory(true);
    }
  },

  openEmployeeInventory() {
    this.showScreen("employeeInventoryScreen");
  },

  updateSyncBadge(syncInfo) {
    const homeEl = document.getElementById("homeSyncText");
    if (homeEl && syncInfo) {
      const count = syncInfo.inventory_count !== undefined ? `${syncInfo.inventory_count} items` : "Ready";
      const timeStr = syncInfo.synced_at ? syncInfo.synced_at.slice(11, 19) : "Now";
      homeEl.textContent = `Google Sheets • ${count} (${timeStr})`;
    }
  },

  updateUserHeader() {
    const badge = document.getElementById("userBadge");
    const nameSpan = document.getElementById("userName");
    const roleSpan = document.getElementById("userRole");
    const adminShortcut = document.getElementById("adminShortcut");

    if (this.state.currentUser) {
      badge.classList.remove("hidden");
      nameSpan.textContent = this.state.currentUser.full_name || this.state.currentUser.username;
      roleSpan.textContent = this.state.currentUser.role;
      if (this.state.currentUser.role === "admin") {
        adminShortcut.classList.remove("hidden");
      } else {
        adminShortcut.classList.add("hidden");
      }
    } else {
      badge.classList.add("hidden");
      adminShortcut.classList.add("hidden");
    }
  },

  // ----------------- AUTHENTICATION -----------------
  async handleLogin() {
    const u = document.getElementById("loginUsername").value.trim();
    const p = document.getElementById("loginPassword").value.trim();
    const submitBtn = document.getElementById("loginSubmitBtn");

    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner"></span><span>Signing in...</span>`;

    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: u, password: p })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.state.currentUser = data.user;
        localStorage.setItem("godrej_user", JSON.stringify(data.user));
        this.updateUserHeader();
        if (data.sync_info) {
          this.updateSyncBadge(data.sync_info);
        }
        const syncedCount = data.sync_info?.inventory_count ?? 0;
        this.showToast(`Welcome, ${data.user.full_name} • ${syncedCount} items synced`, "success");
        this.showScreen("employeeScreen");
      } else {
        this.showToast(data.detail || "Invalid login credentials", "error");
      }
    } catch (err) {
      this.showToast("Connection error. Check network.", "error");
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span>Continue</span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>`;
    }
  },

  handleLogout() {
    this.state.currentUser = null;
    localStorage.removeItem("godrej_user");
    this.updateUserHeader();
    this.showScreen("loginScreen");
    this.showToast("Signed out");
  },

  // ----------------- MODE & SCANNING -----------------
  openMode(mode) {
    this.state.currentMode = mode;
    this.state.stagedBatch = [];
    this.renderStagedList();

    const badge = document.getElementById("activeModeBadge");
    const methodSelector = document.getElementById("methodSelector");
    const processBtnText = document.getElementById("processBtnText");

    badge.className = "mode-pill";
    if (mode === "IN") {
      badge.classList.add("in-pill");
      badge.textContent = "IN • Stock Arrival";
      methodSelector.style.display = "flex";
      processBtnText.textContent = "Commit Inward Stock";
      this.setMethod("SLIP");
    } else if (mode === "OUT") {
      badge.classList.add("out-pill");
      badge.textContent = "OUT • Dispatch";
      methodSelector.style.display = "none";
      processBtnText.textContent = "Deduct Outgoing Stock";
      this.setMethod("SLIP");
    } else if (mode === "CAME_IN_AND_WENT_OUT") {
      badge.classList.add("transit-pill");
      badge.textContent = "Transit • In & Out";
      methodSelector.style.display = "flex";
      processBtnText.textContent = "Record Transit Batch";
      this.setMethod("SLIP");
    }

    this.showScreen("scanScreen");
  },

  setMethod(method) {
    this.state.currentMethod = method;
    const btnSlip = document.getElementById("btnMethodSlip");
    const btnBill = document.getElementById("btnMethodBill");
    const slipActions = document.getElementById("slipCaptureActions");
    const billActions = document.getElementById("billCaptureActions");

    if (method === "SLIP") {
      btnSlip.classList.add("active");
      btnBill.classList.remove("active");
      slipActions.classList.remove("hidden");
      billActions.classList.add("hidden");
    } else {
      btnSlip.classList.remove("active");
      btnBill.classList.add("active");
      slipActions.classList.add("hidden");
      billActions.classList.remove("hidden");
    }
  },

  async compressImage(file, maxDimension = 1000, quality = 0.8) {
    if (window.createImageBitmap) {
      try {
        const bitmap = await createImageBitmap(file);
        let width = bitmap.width;
        let height = bitmap.height;
        if (width > height) {
          if (width > maxDimension) {
            height = Math.round((height * maxDimension) / width);
            width = maxDimension;
          }
        } else if (height > maxDimension) {
          width = Math.round((width * maxDimension) / height);
          height = maxDimension;
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(bitmap, 0, 0, width, height);
        bitmap.close();
        const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", quality));
        if (blob) {
          return new File([blob], file.name || "scan.jpg", { type: "image/jpeg" });
        }
      } catch (e) {
        // Fallback to FileReader below
      }
    }
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        const img = new Image();
        img.onload = () => {
          let width = img.width;
          let height = img.height;

          if (width > height) {
            if (width > maxDimension) {
              height = Math.round((height * maxDimension) / width);
              width = maxDimension;
            }
          } else {
            if (height > maxDimension) {
              width = Math.round((width * maxDimension) / height);
              height = maxDimension;
            }
          }

          const canvas = document.createElement("canvas");
          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0, width, height);

          canvas.toBlob(
            (blob) => {
              if (blob) {
                resolve(new File([blob], file.name || "scan.jpg", { type: "image/jpeg" }));
              } else {
                resolve(file);
              }
            },
            "image/jpeg",
            quality
          );
        };
        img.onerror = () => resolve(file);
        img.src = event.target.result;
      };
      reader.onerror = () => resolve(file);
      reader.readAsDataURL(file);
    });
  },

  async handleSlipPhoto(e) {
    let file = e.target.files[0];
    if (!file) return;

    this.showLoading(true, "Compressing slip...");
    try {
      file = await this.compressImage(file, 900, 0.8);
    } catch (err) {}

    this.showLoading(true, "Reading slip with Vision AI...");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/scan-slip", {
        method: "POST",
        body: formData
      });
      const data = await res.json();

      if (data.success) {
        this.playSuccessSound();
        const p = data.product;
        this.addStagedItem({
          ln_code: data.ln_code,
          description: p.description,
          sku: p.sku,
          category: p.category,
          sub_cat: p.sub_cat,
          dealer_price: p.dealer_price,
          consumer_price: p.consumer_price,
          quantity: 1,
          thumbnail: data.thumbnail || "",
          catalog_match: data.catalog_match
        });
        this.showToast(`Matched: ${p.description}`, "success");
      } else {
        this.showToast(data.error || "Could not read LN code on slip", "error");
      }
    } catch (err) {
      this.showToast("Network error uploading slip photo", "error");
    } finally {
      this.showLoading(false);
      e.target.value = "";
    }
  },

  async handleBillPhoto(e) {
    let file = e.target.files[0];
    if (!file) return;

    this.showLoading(true, "Compressing invoice...");
    try {
      file = await this.compressImage(file, 1400, 0.85);
    } catch (err) {}

    this.showLoading(true, "Extracting bill rows with Vision AI...");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/scan-bill", {
        method: "POST",
        body: formData
      });
      const data = await res.json();

      if (data.success && data.items && data.items.length > 0) {
        this.playSuccessSound();
        data.items.forEach(it => {
          this.addStagedItem({
            ln_code: it.ln_code,
            description: it.description,
            sku: it.sku,
            category: it.category,
            sub_cat: it.sub_cat,
            dealer_price: it.dealer_price,
            consumer_price: it.consumer_price,
            quantity: it.quantity,
            thumbnail: "",
            catalog_match: it.catalog_match,
            invoice_no: data.invoice_no
          });
        });
        this.showToast(`Extracted ${data.total_units} units from Invoice #${data.invoice_no}`, "success");
      } else {
        this.showToast(data.error || "No items detected on invoice image", "error");
      }
    } catch (err) {
      this.showToast("Error processing bill photo", "error");
    } finally {
      this.showLoading(false);
      e.target.value = "";
    }
  },

  async addManualCode() {
    const input = document.getElementById("manualLnInput");
    const code = input.value.trim().toUpperCase();
    if (!code) return;

    this.showLoading(true, "Looking up LN code...");
    try {
      const res = await fetch(`/api/lookup/${encodeURIComponent(code)}`);
      const data = await res.json();
      if (data.found) {
        this.playSuccessSound();
        const it = data.item;
        this.addStagedItem({
          ln_code: it.ln_code,
          description: it.description,
          sku: it.sku,
          category: it.category,
          sub_cat: it.sub_cat,
          dealer_price: it.dealer_price,
          consumer_price: it.consumer_price,
          quantity: 1,
          thumbnail: "",
          catalog_match: true
        });
        input.value = "";
        this.showToast(`Added: ${it.description}`, "success");
      } else {
        this.addStagedItem({
          ln_code: code,
          description: "Unlisted Item",
          sku: "MANUAL",
          category: "General",
          sub_cat: "",
          dealer_price: 0,
          consumer_price: 0,
          quantity: 1,
          thumbnail: "",
          catalog_match: false
        });
        input.value = "";
        this.showToast(`Unlisted code ${code} staged`, "info");
      }
    } catch (e) {
      this.showToast("Lookup failed", "error");
    } finally {
      this.showLoading(false);
    }
  },

  addStagedItem(item) {
    const existingIndex = this.state.stagedBatch.findIndex(x => x.ln_code === item.ln_code);
    if (existingIndex > -1) {
      this.state.stagedBatch[existingIndex].quantity += item.quantity || 1;
      if (item.thumbnail) {
        this.state.stagedBatch[existingIndex].thumbnail = item.thumbnail;
      }
    } else {
      this.state.stagedBatch.unshift(item);
    }
    this.renderStagedList();
  },

  updateQuantity(index, delta) {
    const it = this.state.stagedBatch[index];
    if (!it) return;
    it.quantity = Math.max(1, it.quantity + delta);
    this.renderStagedList();
  },

  removeStagedItem(index) {
    this.state.stagedBatch.splice(index, 1);
    this.renderStagedList();
  },

  clearBatch() {
    if (confirm("Clear all items currently in this staging batch?")) {
      this.state.stagedBatch = [];
      this.renderStagedList();
    }
  },

  renderStagedList() {
    const container = document.getElementById("stagedList");
    const countSpan = document.getElementById("batchCount");
    const footer = document.getElementById("batchFooter");
    const clearBtn = document.getElementById("clearBatchBtn");

    const totalUnits = this.state.stagedBatch.reduce((sum, it) => sum + it.quantity, 0);
    countSpan.textContent = totalUnits;

    if (this.state.stagedBatch.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <p>No items staged yet</p>
          <span>Snap a photo or enter an LN code above to build your batch</span>
        </div>
      `;
      footer.classList.add("hidden");
      clearBtn.style.display = "none";
      return;
    }

    footer.classList.remove("hidden");
    clearBtn.style.display = "inline-block";

    container.innerHTML = this.state.stagedBatch.map((it, idx) => `
      <div class="staged-card">
        ${it.thumbnail ? `<img src="${it.thumbnail}" class="staged-thumb" alt="Slip Thumbnail">` : `
          <div class="staged-thumb" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:1rem;">📦</div>
        `}
        <div class="staged-details">
          <div class="staged-name">${this.escapeHtml(it.description)}</div>
          <div class="staged-meta">
            <span class="staged-code">${it.ln_code}</span>
            ${(this.state.currentUser?.role === 'admin' && it.dealer_price) ? `<span>• ₹${it.dealer_price.toLocaleString('en-IN')}</span>` : ''}
            ${!it.catalog_match ? `<span style="color:#f59e0b;font-weight:600;">(Unlisted)</span>` : ''}
          </div>
        </div>
        <div class="staged-qty-box">
          <button class="qty-btn" onclick="App.updateQuantity(${idx}, -1)">-</button>
          <span class="qty-val">${it.quantity}</span>
          <button class="qty-btn" onclick="App.updateQuantity(${idx}, 1)">+</button>
        </div>
        <button class="btn-remove-item" onclick="App.removeStagedItem(${idx})" title="Remove item">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>
      </div>
    `).join("");
  },

  async submitBatch() {
    if (this.state.stagedBatch.length === 0) return;

    const btn = document.getElementById("processBatchBtn");
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner" style="border-top-color:#fff;"></span><span>Committing to Google Sheets...</span>`;

    const payload = {
      username: this.state.currentUser.username,
      action: this.state.currentMode,
      source: this.state.currentMethod === "SLIP" ? "SLIP_BATCH" : "BILL_PHOTO",
      items: this.state.stagedBatch.map(it => ({
        ln_code: it.ln_code,
        description: it.description,
        sku: it.sku,
        category: it.category,
        sub_cat: it.sub_cat,
        quantity: it.quantity,
        dealer_price: it.dealer_price,
        consumer_price: it.consumer_price
      })),
      invoice_no: this.state.stagedBatch[0]?.invoice_no || null
    };

    try {
      const res = await fetch("/api/process-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      if (res.ok && data.success) {
        this.playSuccessSound();
        let toastMsg = `Saved ${data.processed.length} items to Google Sheets`;
        this.showToast(toastMsg, "success");
        this.state.stagedBatch = [];
        this.renderStagedList();
        setTimeout(() => this.showScreen("employeeScreen"), 700);
      } else {
        this.showToast(data.detail || "Failed to commit inventory batch", "error");
      }
    } catch (e) {
      this.showToast("Network error submitting batch", "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<span id="processBtnText">Commit Batch to Inventory</span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    }
  },

  showLoading(visible, msg = "Processing...") {
    const el = document.getElementById("scanLoading");
    const txt = document.getElementById("loadingMessage");
    if (visible) {
      txt.textContent = msg;
      el.classList.remove("hidden");
    } else {
      el.classList.add("hidden");
    }
  },

  // ----------------- ADMIN DASHBOARD -----------------
  switchAdminTab(tabId) {
    document.querySelectorAll(".admin-tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".admin-content").forEach(c => c.classList.remove("active"));
    
    event.target.classList.add("active");
    const content = document.getElementById(tabId);
    if (content) content.classList.add("active");

    if (tabId === "backupsTab") this.loadBackups();
    if (tabId === "logsTab") this.loadAuditLogs(true);
    if (tabId === "usersTab") this.loadUsers(true);
  },

  async loadInventory(forceRefresh = false) {
    const tbody = document.getElementById("inventoryTableBody");
    const empContainer = document.getElementById("empInventoryList");
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center">${this.inlineLoaderHtml("Syncing sheet...")}</td></tr>`;
    if (empContainer) empContainer.innerHTML = `<div class="loading-placeholder">${this.inlineLoaderHtml("Syncing sheet...")}</div>`;

    this.state.empVisibleCount = this.state.empPageSize;
    this.state.adminVisibleCount = this.state.adminPageSize;

    try {
      const role = this.state.currentUser?.role === "admin" ? "admin" : "employee";
      const empExcelLink = document.getElementById("empExcelLink");
      if (empExcelLink) empExcelLink.href = `/api/export-excel?role=${encodeURIComponent(role)}`;
      const url = `/api/inventory?role=${encodeURIComponent(role)}${forceRefresh ? "&refresh=1" : ""}`;
      const res = await fetch(url);
      const data = await res.json();
      this.state.inventoryData = data.inventory || [];
      
      const totalUnits = this.state.inventoryData.reduce((acc, it) => acc + (Number(it.current_stock) > 0 ? Number(it.current_stock) : 0), 0);
      const itemsCountEl = document.getElementById("empTotalItemsCount");
      const unitsCountEl = document.getElementById("empTotalUnitsCount");
      if (itemsCountEl) itemsCountEl.textContent = this.state.inventoryData.length;
      if (unitsCountEl) unitsCountEl.textContent = totalUnits.toLocaleString('en-IN');

      const subEl = document.getElementById("empSyncedSubtitle");
      if (subEl && data.synced_at) {
        subEl.textContent = `Google Sheets Primary • Synced ${data.synced_at.slice(11, 19)}`;
      }
      this.updateSyncBadge({ inventory_count: this.state.inventoryData.length, synced_at: data.synced_at });

      this.applyAdminFilter(true);
      this.applyEmpFilter(true);
    } catch (e) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center" style="color:var(--color-out)">Failed to load inventory</td></tr>`;
      if (empContainer) empContainer.innerHTML = `<div class="loading-placeholder" style="color:var(--color-out)">Failed to load inventory</div>`;
    }
  },

  renderEmployeeInventory(items, resetWindow = false) {
    if (resetWindow) {
      this.state.empVisibleCount = this.state.empPageSize;
    }
    const container = document.getElementById("empInventoryList");
    const pagWrap = document.getElementById("empInventoryPagination");
    if (!container) return;

    if (items.length === 0) {
      container.innerHTML = `
        <div class="empty-inventory-state">
          <p style="font-weight:600;font-size:0.95rem;color:var(--text-secondary);">No matching stock found</p>
          <span style="font-size:0.8rem;color:var(--text-muted);">Try another search query or scan IN incoming stock</span>
        </div>
      `;
      if (pagWrap) pagWrap.innerHTML = "";
      return;
    }

    const visible = items.slice(0, this.state.empVisibleCount);
    const isAdmin = this.state.currentUser?.role === "admin";

    container.innerHTML = visible.map(it => {
      const stock = Number(it.current_stock || 0);
      const isPositive = stock > 0;
      const stockBadge = isPositive
        ? `<span class="stock-badge in-stock">${stock} in stock</span>`
        : `<span class="stock-badge out-stock">0 stock</span>`;

      const priceHtml = isAdmin
        ? `
            <div class="price-group">
              <div class="price-box">
                <span class="price-lbl">Dealer</span>
                <span class="price-val">${it.dealer_price != null ? `₹${Number(it.dealer_price || 0).toLocaleString('en-IN')}` : '—'}</span>
              </div>
              <div class="price-box">
                <span class="price-lbl">Consumer</span>
                <span class="price-val">${it.consumer_price != null ? `₹${Number(it.consumer_price || 0).toLocaleString('en-IN')}` : '—'}</span>
              </div>
            </div>
          `
        : "";

      return `
        <div class="emp-inventory-card">
          <div>
            <div class="emp-inv-header">
              <span class="emp-inv-code">${this.escapeHtml(it.ln_code)}</span>
              ${stockBadge}
            </div>
            <div class="emp-inv-body">
              <h4 class="emp-inv-title">${this.escapeHtml(it.description || 'Godrej Item')}</h4>
              <div class="emp-inv-meta">
                <span class="meta-tag">${this.escapeHtml(it.category || 'Godrej Interio')}</span>
                ${it.sub_cat ? `<span class="meta-tag">${this.escapeHtml(it.sub_cat)}</span>` : ''}
              </div>
            </div>
          </div>
          <div class="emp-inv-footer">
            ${priceHtml}
            <div style="display:flex;align-items:center;gap:0.6rem;margin-left:auto;">
              <div class="updated-box">
                <span class="updated-time">${it.last_updated ? it.last_updated.slice(0, 16) : 'Catalog'}</span>
                <span class="updated-user">${this.escapeHtml(it.last_updated_by || 'system')}</span>
              </div>
              <button type="button" class="btn-delete-stock" onclick="App.openDeleteStockModal('${this.escapeHtml(it.ln_code)}')" title="Delete stock from Google Sheet">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                <span>Delete</span>
              </button>
            </div>
          </div>
        </div>
      `;
    }).join("");

    if (pagWrap) {
      const remaining = items.length - visible.length;
      if (remaining > 0) {
        pagWrap.innerHTML = `
          <div class="pagination-meta">Showing ${visible.length} of ${items.length} items</div>
          <button class="btn-load-more" onclick="App.loadMoreEmpInventory()">Load ${Math.min(remaining, this.state.empPageSize)} More (${remaining} left)</button>
        `;
      } else if (items.length > this.state.empPageSize) {
        pagWrap.innerHTML = `<div class="pagination-meta">Showing all ${items.length} items</div>`;
      } else {
        pagWrap.innerHTML = "";
      }
    }
  },

  loadMoreEmpInventory() {
    this.state.empVisibleCount += this.state.empPageSize;
    this.applyEmpFilter(false);
  },

  setInventoryFilter(filterType, btnEl) {
    this.state.inventoryFilter = filterType;
    if (btnEl && btnEl.parentElement) {
      btnEl.parentElement.querySelectorAll(".filter-pill").forEach(p => p.classList.remove("active"));
      btnEl.classList.add("active");
    }
    this.applyEmpFilter(true);
  },

  applyEmpFilter(resetWindow = true) {
    const input = document.getElementById("empInventorySearchInput");
    const query = input ? input.value.trim().toLowerCase() : "";
    const filterType = this.state.inventoryFilter || "all";

    let list = this.state.inventoryData || [];

    if (filterType === "in_stock") {
      list = list.filter(it => Number(it.current_stock || 0) > 0);
    } else if (filterType === "out_of_stock") {
      list = list.filter(it => Number(it.current_stock || 0) <= 0);
    }

    if (query) {
      list = list.filter(it =>
        (it.ln_code && it.ln_code.toLowerCase().includes(query)) ||
        (it.description && it.description.toLowerCase().includes(query)) ||
        (it.category && it.category.toLowerCase().includes(query)) ||
        (it.sub_cat && it.sub_cat.toLowerCase().includes(query))
      );
    }

    this.renderEmployeeInventory(list, resetWindow);
  },

  filterEmpInventory() {
    clearTimeout(this.state.searchDebounceTimer);
    this.state.searchDebounceTimer = setTimeout(() => {
      this.applyEmpFilter(true);
    }, 120);
  },

  async refreshFromSheets(btnEl, silent = false) {
    const btn = btnEl || null;
    const origHtml = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span><span>Syncing...</span>`;
    }

    try {
      const res = await fetch("/api/sync-from-sheets", { method: "POST" });
      const data = await res.json();
      if (res.ok && data.success) {
        if (data.sync_info) {
          this.updateSyncBadge(data.sync_info);
        }
        if (!silent) {
          this.playSuccessSound();
          this.showToast(data.message, "success");
        }
        await this.loadInventory(false);
      } else if (!silent) {
        this.showToast(data.detail || "Refresh from Google Sheet failed", "error");
      }
    } catch (e) {
      if (!silent) this.showToast("Network error refreshing Google Sheet", "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origHtml;
      }
    }
  },

  renderInventoryTable(items, resetWindow = false) {
    if (resetWindow) {
      this.state.adminVisibleCount = this.state.adminPageSize;
    }
    const tbody = document.getElementById("inventoryTableBody");
    const pagWrap = document.getElementById("adminInventoryPagination");
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="color:var(--text-muted);">No inventory records found yet.</td></tr>`;
      if (pagWrap) pagWrap.innerHTML = "";
      return;
    }

    const visible = items.slice(0, this.state.adminVisibleCount);
    const isAdmin = this.state.currentUser?.role === "admin";
    tbody.innerHTML = visible.map(it => `
      <tr>
        <td style="font-family:var(--font-mono);font-weight:600;color:var(--accent-code);">${it.ln_code}</td>
        <td><strong style="font-weight:600;">${this.escapeHtml(it.description)}</strong></td>
        <td><span style="font-family:var(--font-mono);font-weight:700;color:${it.current_stock > 0 ? 'var(--color-in)' : 'var(--color-out)'}">${it.current_stock}</span></td>
        <td style="color:var(--text-secondary);">${this.escapeHtml(it.category || 'General')}</td>
        <td style="font-family:var(--font-mono);">${(isAdmin && it.dealer_price != null) ? `₹${Number(it.dealer_price || 0).toLocaleString('en-IN')}` : '—'}</td>
        <td style="font-family:var(--font-mono);">${(isAdmin && it.consumer_price != null) ? `₹${Number(it.consumer_price || 0).toLocaleString('en-IN')}` : '—'}</td>
        <td style="font-size:0.78rem;color:var(--text-muted);">${it.last_updated ? it.last_updated.slice(0, 16) : ''} (${this.escapeHtml(it.last_updated_by || 'system')})</td>
        <td style="text-align:right;">
          <button type="button" class="btn-delete-stock" onclick="App.openDeleteStockModal('${this.escapeHtml(it.ln_code)}')" title="Delete stock from Google Sheet">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            <span>Delete</span>
          </button>
        </td>
      </tr>
    `).join("");

    if (pagWrap) {
      const remaining = items.length - visible.length;
      if (remaining > 0) {
        pagWrap.innerHTML = `
          <div class="pagination-meta">Showing ${visible.length} of ${items.length} items</div>
          <button class="btn-load-more" onclick="App.loadMoreAdminInventory()">Load ${Math.min(remaining, this.state.adminPageSize)} More (${remaining} left)</button>
        `;
      } else if (items.length > this.state.adminPageSize) {
        pagWrap.innerHTML = `<div class="pagination-meta">Showing all ${items.length} items</div>`;
      } else {
        pagWrap.innerHTML = "";
      }
    }
  },

  loadMoreAdminInventory() {
    this.state.adminVisibleCount += this.state.adminPageSize;
    this.applyAdminFilter(false);
  },

  applyAdminFilter(resetWindow = true) {
    const query = (document.getElementById("inventorySearchInput")?.value || "").trim().toLowerCase();
    const filtered = this.state.inventoryData.filter(it =>
      it.ln_code.toLowerCase().includes(query) ||
      (it.description && it.description.toLowerCase().includes(query)) ||
      (it.category && it.category.toLowerCase().includes(query)) ||
      (it.sub_cat && it.sub_cat.toLowerCase().includes(query))
    );
    this.renderInventoryTable(filtered, resetWindow);
  },

  filterInventory() {
    clearTimeout(this.state.adminSearchDebounceTimer);
    this.state.adminSearchDebounceTimer = setTimeout(() => {
      this.applyAdminFilter(true);
    }, 120);
  },

  async loadAuditLogs(forceRefresh = false) {
    const tbody = document.getElementById("logsTableBody");
    tbody.innerHTML = `<tr><td colspan="8" class="text-center">${this.inlineLoaderHtml("Loading logs...")}</td></tr>`;
    const actionFilter = document.getElementById("logActionFilter").value;

    try {
      const params = new URLSearchParams();
      if (actionFilter) params.set("action", actionFilter);
      if (forceRefresh) params.set("refresh", "1");
      const qs = params.toString() ? `?${params.toString()}` : "";
      const res = await fetch(`/api/logs${qs}`);
      const data = await res.json();
      const logs = data.logs || [];

      if (logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="color:var(--text-muted);">No audit logs recorded yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = logs.map(l => {
        let badgeStyle = "background:var(--color-in-bg);color:var(--color-in);border:1px solid var(--color-in-border);";
        if (l.action === "OUT" || l.action === "DELETE") badgeStyle = "background:var(--color-out-bg);color:var(--color-out);border:1px solid var(--color-out-border);";
        if (l.action === "CAME_IN_AND_WENT_OUT") badgeStyle = "background:var(--color-transit-bg);color:var(--color-transit);border:1px solid var(--color-transit-border);";

        return `
          <tr>
            <td style="font-size:0.75rem;color:var(--text-muted);">${l.timestamp.slice(0, 19)}</td>
            <td><strong style="font-weight:600;">${this.escapeHtml(l.employee_username)}</strong></td>
            <td><span style="${badgeStyle}padding:2px 7px;border-radius:999px;font-weight:600;font-size:0.7rem;">${l.action}</span></td>
            <td style="font-size:0.78rem;color:var(--text-secondary);">${l.source}</td>
            <td style="font-family:var(--font-mono);color:var(--accent-code);font-weight:600;">${l.ln_code}</td>
            <td>${this.escapeHtml(l.description || '')}</td>
            <td style="font-family:var(--font-mono);"><strong>${l.quantity}</strong></td>
            <td style="font-family:var(--font-mono);font-size:0.78rem;color:var(--text-secondary);">${l.stock_before} → ${l.stock_after}</td>
          </tr>
        `;
      }).join("");
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="color:var(--color-out)">Failed to load logs</td></tr>`;
    }
  },

  openDeleteStockModal(lnCode) {
    const item = (this.state.inventoryData || []).find(it => it.ln_code === lnCode);
    if (!item) {
      this.showToast(`Item ${lnCode} not found`, "error");
      return;
    }
    this.state.pendingDeleteItem = item;
    const codeEl = document.getElementById("deleteModalLnCode");
    const descEl = document.getElementById("deleteModalDesc");
    const badgeEl = document.getElementById("deleteModalStockBadge");
    if (codeEl) codeEl.textContent = item.ln_code;
    if (descEl) descEl.textContent = item.description || "Godrej Item";
    if (badgeEl) {
      const st = Number(item.current_stock || 0);
      badgeEl.textContent = `${st} in stock`;
      badgeEl.className = st > 0 ? "stock-badge in-stock" : "stock-badge out-stock";
    }
    document.getElementById("deleteStockModal").classList.remove("hidden");
  },

  hideDeleteStockModal() {
    this.state.pendingDeleteItem = null;
    document.getElementById("deleteStockModal").classList.add("hidden");
  },

  async confirmDeleteStock() {
    const item = this.state.pendingDeleteItem;
    if (!item) return;

    const btn = document.getElementById("confirmDeleteStockBtn");
    const origHtml = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner" style="border-top-color:#fff;"></span><span>Deleting...</span>`;
    }

    try {
      const username = this.state.currentUser?.username || "admin";
      const res = await fetch(`/api/inventory/${encodeURIComponent(item.ln_code)}?username=${encodeURIComponent(username)}`, {
        method: "DELETE"
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.playSuccessSound();
        this.showToast(data.message || `Deleted ${item.ln_code} from Google Sheet`, "success");
        this.hideDeleteStockModal();
        await this.loadInventory(true);
      } else {
        this.showToast(data.detail || "Failed to delete stock item", "error");
      }
    } catch (e) {
      this.showToast("Network error deleting stock item", "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origHtml;
      }
    }
  },

  async loadUsers(forceRefresh = false) {
    const container = document.getElementById("usersListContainer");
    try {
      const url = forceRefresh ? "/api/users?refresh=1" : "/api/users";
      const res = await fetch(url);
      const data = await res.json();
      const users = data.users || [];

      container.innerHTML = users.map(u => `
        <div class="user-item-card">
          <div>
            <div class="user-item-name">${this.escapeHtml(u.full_name)} <span style="font-weight:400;color:var(--text-muted);">(@${this.escapeHtml(u.username)})</span></div>
            <div class="user-item-role">${u.role.toUpperCase()} • Joined ${u.created_at.slice(0,10)}${u.username === "admin" ? " • Primary Admin" : ""}</div>
          </div>
          <div class="user-actions-group">
            <button type="button" class="btn btn-secondary btn-sm" onclick="App.openChangePasswordModal(${u.id}, '${this.escapeHtml(u.username)}', '${this.escapeHtml(u.full_name).replace(/'/g, "\\'")}')">
              Change Password
            </button>
            ${u.username !== "admin" ? `
              <button type="button" class="btn btn-secondary btn-sm" onclick="App.deleteUser(${u.id})" style="color:var(--color-out);">Delete</button>
            ` : ""}
          </div>
        </div>
      `).join("");
    } catch (e) {
      container.innerHTML = `<p style="color:var(--color-out)">Could not load users list</p>`;
    }
  },

  openChangePasswordModal(userId, username, fullName) {
    document.getElementById("changePwdUserId").value = String(userId);
    const lbl = document.getElementById("changePwdUserLabel");
    if (lbl) lbl.textContent = `${fullName} (@${username})`;
    document.getElementById("changePwdNewInput").value = "";
    document.getElementById("changePwdConfirmInput").value = "";
    document.getElementById("changePasswordModal").classList.remove("hidden");
  },

  hideChangePasswordModal() {
    document.getElementById("changePasswordModal").classList.add("hidden");
  },

  async submitChangePassword(e) {
    e.preventDefault();
    const userId = document.getElementById("changePwdUserId").value;
    const newPassword = document.getElementById("changePwdNewInput").value.trim();
    const confirmPassword = document.getElementById("changePwdConfirmInput").value.trim();

    if (newPassword.length < 4) {
      this.showToast("Password must be at least 4 characters", "error");
      return;
    }
    if (newPassword !== confirmPassword) {
      this.showToast("Passwords do not match", "error");
      return;
    }

    const btn = document.getElementById("changePwdSubmitBtn");
    const origHtml = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner" style="border-top-color:#fff;"></span><span>Updating...</span>`;
    }

    try {
      const res = await fetch(`/api/users/${encodeURIComponent(userId)}/password`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: newPassword })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.playSuccessSound();
        this.showToast(data.message || "Password updated in Google Sheets", "success");
        this.hideChangePasswordModal();
      } else {
        this.showToast(data.detail || "Failed to update password", "error");
      }
    } catch (err) {
      this.showToast("Network error updating password", "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origHtml;
      }
    }
  },

  showAddUserModal() {
    document.getElementById("addUserModal").classList.remove("hidden");
  },

  hideAddUserModal() {
    document.getElementById("addUserModal").classList.add("hidden");
  },

  async submitAddUser(e) {
    e.preventDefault();
    const full_name = document.getElementById("newFullName").value.trim();
    const username = document.getElementById("newUsername").value.trim();
    const password = document.getElementById("newPassword").value.trim();
    const role = document.getElementById("newRole").value;

    try {
      const res = await fetch("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name, username, password, role })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.showToast(`User @${username} created`, "success");
        this.hideAddUserModal();
        document.getElementById("addUserForm").reset();
        this.loadUsers();
      } else {
        this.showToast(data.detail || "Failed to create user", "error");
      }
    } catch (err) {
      this.showToast("Network error creating user", "error");
    }
  },

  async deleteUser(userId) {
    if (!confirm("Are you sure you want to remove this employee account?")) return;
    try {
      const res = await fetch(`/api/users/${userId}`, { method: "DELETE" });
      const data = await res.json();
      if (res.ok) {
        this.showToast("User deleted", "info");
        this.loadUsers();
      } else {
        this.showToast(data.detail || "Error deleting user", "error");
      }
    } catch (e) {
      this.showToast("Failed to delete user", "error");
    }
  },

  async loadBackups() {
    const listEl = document.getElementById("backupHistoryList");
    const lastAtEl = document.getElementById("lastBackupAtText");
    const lastAutoEl = document.getElementById("lastAutoBackupText");
    if (!listEl) return;

    try {
      const res = await fetch("/api/backups");
      const data = await res.json();
      if (lastAtEl) lastAtEl.textContent = data.last_backup_at || "Never";
      if (lastAutoEl) lastAutoEl.textContent = data.last_auto_backup_date || "Pending";

      const snaps = data.snapshots || [];
      if (snaps.length === 0) {
        listEl.innerHTML = `<p style="color:var(--text-muted);font-size:0.82rem;">No snapshots saved yet.</p>`;
        return;
      }

      listEl.innerHTML = snaps.map(s => `
        <div class="snapshot-row">
          <div>
            <div style="font-family:var(--font-mono);font-weight:600;font-size:0.82rem;color:var(--accent-code);">${this.escapeHtml(s.backup_id)}</div>
            <div style="font-size:0.74rem;color:var(--text-muted);">${this.escapeHtml(s.timestamp)}</div>
          </div>
          <div style="text-align:right;">
            <div style="font-family:var(--font-mono);font-weight:700;font-size:0.85rem;">${s.total_units} units</div>
            <div style="font-size:0.72rem;color:var(--text-muted);">${s.item_count} SKUs</div>
          </div>
        </div>
      `).join("");
    } catch (e) {
      listEl.innerHTML = `<p style="color:var(--color-out);font-size:0.82rem;">Failed to load backup snapshots.</p>`;
    }
  },

  async createBackupNow(btnEl) {
    const orig = btnEl ? btnEl.innerHTML : "";
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.innerHTML = `<span class="spinner" style="border-top-color:#fff;"></span><span>Saving...</span>`;
    }
    try {
      const res = await fetch("/api/backup-now", { method: "POST" });
      const data = await res.json();
      if (res.ok && data.success) {
        this.playSuccessSound();
        this.showToast(data.message, "success");
        await this.loadBackups();
      } else {
        this.showToast(data.detail || "Backup failed", "error");
      }
    } catch (e) {
      this.showToast("Network error creating backup", "error");
    } finally {
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.innerHTML = orig;
      }
    }
  },

  async restoreFromBackup(btnEl) {
    if (!confirm("Restore Live_Inventory from Backup_Latest? This replaces current Live_Inventory rows with the last saved Backup_Latest snapshot.")) return;
    const orig = btnEl ? btnEl.innerHTML : "";
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.innerHTML = `<span class="spinner"></span><span>Restoring...</span>`;
    }
    try {
      const res = await fetch("/api/restore-backup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: this.state.currentUser?.username || "admin" })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.playSuccessSound();
        this.showToast(data.message, "success");
        await this.loadInventory(true);
        await this.loadAuditLogs(true);
      } else {
        this.showToast(data.detail || "Restore failed", "error");
      }
    } catch (e) {
      this.showToast("Network error during restore", "error");
    } finally {
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.innerHTML = orig;
      }
    }
  },

  async loadSettings() {
    try {
      const res = await fetch("/api/settings");
      const data = await res.json();
      document.getElementById("catalogCount").textContent = Number(data.total_catalog_items).toLocaleString();
    } catch (e) {}
  },

  async saveSettings() {
    const key = document.getElementById("settingsGroqKey").value.trim();
    if (!key) return;

    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: "groq_api_key", value: key })
      });
      const data = await res.json();
      if (res.ok) {
        this.showToast("API key updated", "success");
        document.getElementById("settingsGroqKey").value = "";
      }
    } catch (e) {
      this.showToast("Failed to save settings", "error");
    }
  },

  escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
};

window.addEventListener("DOMContentLoaded", () => App.init());
