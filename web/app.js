const DEFAULT_ITEMS = [
  "188004500",
  "553971858",
  "553970961",
];


const IGNORED_PLAYER_IDS = new Set([1]);

const itemList = document.getElementById("itemList");
const itemInput = document.getElementById("itemInput");
const addBtn = document.getElementById("addBtn");
const searchBtn = document.getElementById("searchBtn");
const errorBox = document.getElementById("errorBox");
const resultsPanel = document.getElementById("resultsPanel");
const summaryGrid = document.getElementById("summaryGrid");
const matchBadge = document.getElementById("matchBadge");
const playersTable = document.getElementById("playersTable");
const playersBody = document.getElementById("playersBody");
const emptyState = document.getElementById("emptyState");
const spinner = document.getElementById("spinner");

const items = new Set();

function renderItems() {
  itemList.innerHTML = "";
  for (const value of items) {
    const chip = document.createElement("div");
    chip.className = "item-chip";
    chip.innerHTML = `
      <code>${escapeHtml(value)}</code>
      <button type="button" class="chip-remove" aria-label="Remove">×</button>
    `;
    chip.querySelector(".chip-remove").addEventListener("click", () => {
      items.delete(value);
      renderItems();
    });
    itemList.appendChild(chip);
  }
}

const ITEM_DIGITS = /^\d{1,16}$/;
const ITEM_URL = /^https?:\/\/(?:www\.)?rolimons\.com\/item\/\d{1,16}\/?$/i;
const INJECTION_PATTERN = /(<\s*script|javascript:|on\w+\s*=|\.\.\/|%00|\x00|union\s+select|'\s*or\s*'1)/i;

function sanitizeItemToken(raw) {
  const value = raw.trim();
  if (!value || value.length > 256) {
    throw new Error("Некорректный item id");
  }
  if (INJECTION_PATTERN.test(value)) {
    throw new Error("Запрещённые символы во входе");
  }
  if (ITEM_DIGITS.test(value) || ITEM_URL.test(value)) {
    return value;
  }
  throw new Error("Только числовой ID или ссылка Rolimons");
}

function addItem(raw) {
  try {
    const value = sanitizeItemToken(raw);
    items.add(value);
    renderItems();
    itemInput.value = "";
    clearError();
  } catch (error) {
    showError(error.message || "Некорректный item id");
  }
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatNumber(value) {
  if (value == null) {
    return "—";
  }
  return new Intl.NumberFormat("en-US").format(value);
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
}

function clearError() {
  errorBox.textContent = "";
  errorBox.classList.add("hidden");
}

function setLoading(loading) {
  searchBtn.disabled = loading;
  spinner.classList.toggle("hidden", !loading);
}

function renderSummary(itemsData) {
  summaryGrid.innerHTML = itemsData.map((item) => {
    const owners = item.expected_owners
      ? `${item.unique_owners}/${item.expected_owners}`
      : String(item.unique_owners);
    const statusClass = item.complete ? "ok" : "warn";
    const statusText = item.complete ? "complete" : "partial";
    const thumb = item.thumbnail_url
      ? `<img class="item-thumb" src="${escapeHtml(item.thumbnail_url)}" alt="">`
      : `<div class="item-thumb"></div>`;
    return `
      <article class="item-card">
        ${thumb}
        <div>
          <h3>${escapeHtml(item.item_name)}</h3>
          <div class="item-meta">
            <span class="tag">#${item.item_id}</span>
            <span class="tag">owners ${owners}</span>
            <span class="tag ${statusClass}">${statusText}</span>
            ${item.value ? `<span class="tag">value ${formatNumber(item.value)}</span>` : ""}
            ${item.rap ? `<span class="tag">rap ${formatNumber(item.rap)}</span>` : ""}
          </div>
        </div>
      </article>
    `;
  }).join("");
}

function renderPlayers(players) {
  playersBody.innerHTML = players.map((player, index) => {
    const name = player.name ? escapeHtml(player.name) : "Unknown";
    return `
      <tr>
        <td>${index + 1}</td>
        <td class="player-name">${name}</td>
        <td>${player.player_id}</td>
        <td>
          <div class="links">
            <a class="link-btn" href="${player.profile}" target="_blank" rel="noreferrer">Rolimons</a>
            <a class="link-btn alt" href="${player.roblox_profile}" target="_blank" rel="noreferrer">Roblox</a>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

async function search() {
  clearError();
  if (items.size < 2) {
    showError("Добавь минимум 2 предмета.");
    return;
  }

  setLoading(true);
  try {
    const payloadItems = [...items].map((value) => sanitizeItemToken(value));
    const response = await fetch("/api/intersect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: payloadItems,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload.detail || "Request failed";
      if (response.status === 429) {
        const retry = response.headers.get("Retry-After");
        throw new Error(retry ? `Rate limit. Retry in ${retry}s` : "Rate limit exceeded");
      }
      throw new Error(typeof detail === "string" ? detail : "Request failed");
    }

    resultsPanel.classList.remove("hidden");
    renderSummary(payload.items);
    const players = payload.players.filter((player) => !IGNORED_PLAYER_IDS.has(player.player_id));
    matchBadge.textContent = `${players.length} игроков`;
    const hasPlayers = players.length > 0;
    emptyState.classList.toggle("hidden", hasPlayers);
    playersTable.classList.toggle("hidden", !hasPlayers);
    if (hasPlayers) {
      renderPlayers(players);
    } else {
      playersBody.innerHTML = "";
    }
  } catch (error) {
    const message = error.message || "Не удалось выполнить поиск";
    if (message.includes("429") || message.toLowerCase().includes("limit")) {
      showError("Слишком много запросов. Подожди и попробуй снова.");
      return;
    }
    showError(message);
  } finally {
    setLoading(false);
  }
}

addBtn.addEventListener("click", () => addItem(itemInput.value));
itemInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addItem(itemInput.value);
  }
});
searchBtn.addEventListener("click", search);

for (const value of DEFAULT_ITEMS) {
  items.add(value);
}
renderItems();
