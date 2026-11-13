// Godrej Inventory Automation Client Application
const App = {
  state: {
    currentUser: null,
    currentMode: "IN", // 'IN', 'OUT', 'CAME_IN_AND_WENT_OUT'
    currentMethod: "SLIP", // 'SLIP', 'BILL'
    stagedBatch: [],
    inventoryData: [],
    audioCtx: null
  },

  init() {
    this.bindEvents();
    this.checkSession();
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
      osc.frequency.setValueAtTime(880, ctx.currentTime); // High pleasant chime (A5)
      osc.frequency.exponentialRampToValueAtTime(1760, ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.15);
    } catch (e) {
      // Audio autoplay restrictions fallback
    }

    // Phone vibration
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
      this.loadInventory();
      this.loadAuditLogs();
      this.loadUsers();
      this.loadSettings();
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
    submitBtn.innerHTML = `<span>Signing In...</span>`;

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
        this.showToast(`Welcome back, ${data.user.full_name}!`, "success");
        this.showScreen("employeeScreen");
      } else {
        this.showToast(data.detail || "Invalid login credentials", "error");
      }
    } catch (err) {
      this.showToast("Connection error. Check network.", "error");
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span>Sign In</span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>`;
    }
  },

  handleLogout() {
    this.state.currentUser = null;
    localStorage.removeItem("godrej_user");
    this.updateUserHeader();
    this.showScreen("loginScreen");
    this.showToast("Logged out successfully");
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
      badge.textContent = "IN (STOCK ARRIVAL)";
      methodSelector.style.display = "flex";
      processBtnText.textContent = "Process Inward Stock";
      this.setMethod("SLIP");
    } else if (mode === "OUT") {
      badge.classList.add("out-pill");
      badge.textContent = "OUT (DISPATCH)";
      // OUT strictly uses Slips per specifications
      methodSelector.style.display = "none";
      processBtnText.textContent = "Deduct Stock From Inventory";
      this.setMethod("SLIP");
    } else if (mode === "CAME_IN_AND_WENT_OUT") {
      badge.classList.add("transit-pill");
      badge.textContent = "CAME IN & WENT OUT (TRANSIT)";
      methodSelector.style.display = "flex";
      processBtnText.textContent = "Record In & Out Transit";
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

  // Single Cardboard Slip Photo Handler
  async handleSlipPhoto(e) {
    const file = e.target.files[0];
    if (!file) return;

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
        this.showToast(`Found: ${p.description}`, "success");
      } else {
        this.showToast(data.error || "Could not read LN code on this slip", "error");
      }
    } catch (err) {
      this.showToast("Network error uploading slip photo", "error");
    } finally {
      this.showLoading(false);
      e.target.value = ""; // Reset input so same file can be selected again
    }
  },

  // Bill Photo Handler
  async handleBillPhoto(e) {
    const file = e.target.files[0];
    if (!file) return;

    this.showLoading(true, "Analyzing bill table & extracting items...");
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
        this.showToast(data.error || "No items detected on this invoice image", "error");
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

    this.showLoading(true, "Looking up product catalog...");
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
        this.showToast(`Unlisted code ${code} added to batch`, "info");
      }
    } catch (e) {
      this.showToast("Lookup failed", "error");
    } finally {
      this.showLoading(false);
    }
  },

  addStagedItem(item) {
    // If already in batch, increment quantity
    const existingIndex = this.state.stagedBatch.findIndex(x => x.ln_code === item.ln_code);
    if (existingIndex > -1) {
      this.state.stagedBatch[existingIndex].quantity += item.quantity || 1;
      if (item.thumbnail) {
        this.state.stagedBatch[existingIndex].thumbnail = item.thumbnail;
      }
    } else {
      this.state.stagedBatch.unshift(item); // Add to top
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
          <div class="empty-icon">📷</div>
          <p>No items scanned yet.</p>
          <span>Snap a slip photo to see live product match</span>
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
          <div class="staged-thumb" style="display:flex;align-items:center;justify-content:center;color:#64748b;font-size:1.2rem;">📦</div>
        `}
        <div class="staged-details">
          <div class="staged-name">${this.escapeHtml(it.description)}</div>
          <div class="staged-meta">
            <span class="staged-code">${it.ln_code}</span>
            ${it.dealer_price ? `<span>• ₹${it.dealer_price.toLocaleString('en-IN')}</span>` : ''}
            ${!it.catalog_match ? `<span style="color:#f59e0b;font-weight:600;">(Unlisted)</span>` : ''}
          </div>
        </div>
        <div class="staged-qty-box">
          <button class="qty-btn" onclick="App.updateQuantity(${idx}, -1)">-</button>
          <span class="qty-val">${it.quantity}</span>
          <button class="qty-btn" onclick="App.updateQuantity(${idx}, 1)">+</button>
        </div>
        <button class="btn-remove-item" onclick="App.removeStagedItem(${idx})" title="Remove item">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>
      </div>
    `).join("");
  },

  async submitBatch() {
    if (this.state.stagedBatch.length === 0) return;

    const btn = document.getElementById("processBatchBtn");
    btn.disabled = true;
    btn.textContent = "Processing Transaction...";

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
        this.showToast(`Successfully processed ${data.processed.length} items!`, "success");
        this.state.stagedBatch = [];
        this.renderStagedList();
        // Return to main dashboard
        setTimeout(() => this.showScreen("employeeScreen"), 800);
      } else {
        this.showToast(data.detail || "Failed to commit inventory batch", "error");
      }
    } catch (e) {
      this.showToast("Network error submitting batch", "error");
    } finally {
      btn.disabled = false;
      const processBtnText = document.getElementById("processBtnText");
      btn.textContent = processBtnText ? processBtnText.textContent : "Process Batch";
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
  },

  async loadInventory() {
    const tbody = document.getElementById("inventoryTableBody");
    tbody.innerHTML = `<tr><td colspan="6" class="text-center">Loading inventory...</td></tr>`;

    try {
      const res = await fetch("/api/inventory");
      const data = await res.json();
      this.state.inventoryData = data.inventory || [];
      this.renderInventoryTable(this.state.inventoryData);
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color:#f43f5e">Failed to load inventory</td></tr>`;
    }
  },

  renderInventoryTable(items) {
    const tbody = document.getElementById("inventoryTableBody");
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center">No inventory records found yet. Scan IN items to start.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map(it => `
      <tr>
        <td style="font-family:monospace;font-weight:700;color:#38bdf8;">${it.ln_code}</td>
        <td><strong>${this.escapeHtml(it.description)}</strong></td>
        <td><span style="font-size:1.1rem;font-weight:800;color:${it.current_stock > 0 ? '#10b981' : '#f43f5e'}">${it.current_stock}</span></td>
        <td>${this.escapeHtml(it.category || 'General')}</td>
        <td>₹${Number(it.dealer_price || 0).toLocaleString('en-IN')}</td>
        <td style="font-size:0.8rem;color:#94a3b8;">${it.last_updated ? it.last_updated.slice(0, 16) : ''} (${it.last_updated_by || 'system'})</td>
      </tr>
    `).join("");
  },

  filterInventory() {
    const query = document.getElementById("inventorySearchInput").value.toLowerCase();
    const filtered = this.state.inventoryData.filter(it => 
      it.ln_code.toLowerCase().includes(query) ||
      (it.description && it.description.toLowerCase().includes(query)) ||
      (it.sku && it.sku.toLowerCase().includes(query))
    );
    this.renderInventoryTable(filtered);
  },

  async loadAuditLogs() {
    const tbody = document.getElementById("logsTableBody");
    tbody.innerHTML = `<tr><td colspan="8" class="text-center">Loading logs...</td></tr>`;
    const actionFilter = document.getElementById("logActionFilter").value;

    try {
      let url = "/api/logs";
      if (actionFilter) url += `?action=${actionFilter}`;
      const res = await fetch(url);
      const data = await res.json();
      const logs = data.logs || [];

      if (logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center">No audit logs recorded yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = logs.map(l => {
        let badgeColor = "#10b981";
        if (l.action === "OUT") badgeColor = "#f43f5e";
        if (l.action === "CAME_IN_AND_WENT_OUT") badgeColor = "#6366f1";

        return `
          <tr>
            <td style="font-size:0.75rem;color:#94a3b8;">${l.timestamp.slice(0, 19)}</td>
            <td><strong>${this.escapeHtml(l.employee_username)}</strong></td>
            <td><span style="background:${badgeColor}22;color:${badgeColor};padding:3px 8px;border-radius:12px;font-weight:700;font-size:0.75rem;">${l.action}</span></td>
            <td style="font-size:0.8rem;">${l.source}</td>
            <td style="font-family:monospace;color:#38bdf8;">${l.ln_code}</td>
            <td>${this.escapeHtml(l.description || '')}</td>
            <td><strong>${l.quantity}</strong></td>
            <td style="font-size:0.8rem;">${l.stock_before} ➔ ${l.stock_after}</td>
          </tr>
        `;
      }).join("");
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="color:#f43f5e">Failed to load logs</td></tr>`;
    }
  },

  async loadUsers() {
    const container = document.getElementById("usersListContainer");
    try {
      const res = await fetch("/api/users");
      const data = await res.json();
      const users = data.users || [];

      container.innerHTML = users.map(u => `
        <div class="user-item-card">
          <div>
            <div class="user-item-name">${this.escapeHtml(u.full_name)} <span style="font-weight:400;color:#94a3b8;">(@${u.username})</span></div>
            <div class="user-item-role">${u.role.toUpperCase()} • Joined ${u.created_at.slice(0,10)}</div>
          </div>
          ${u.username !== "admin" ? `
            <button class="btn btn-secondary btn-sm" onclick="App.deleteUser(${u.id})" style="color:#f43f5e;">Delete</button>
          ` : `<span style="font-size:0.75rem;color:#94a3b8;font-weight:600;">Main Admin</span>`}
        </div>
      `).join("");
    } catch (e) {
      container.innerHTML = `<p style="color:#f43f5e">Could not load users list</p>`;
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
        this.showToast(`User @${username} created!`, "success");
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
        this.showToast("API key updated successfully", "success");
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
