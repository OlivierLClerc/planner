const DAY_IN_MS = 24 * 60 * 60 * 1000;
const MONDAY_REFERENCE = new Date(Date.UTC(2024, 0, 1));
const draftStateByKey = new Map();

function parseIsoDate(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function toIsoDate(dateValue) {
  return dateValue.toISOString().slice(0, 10);
}

function addDays(dateValue, numberOfDays) {
  return new Date(dateValue.getTime() + numberOfDays * DAY_IN_MS);
}

function monthStart(dateValue) {
  return new Date(Date.UTC(dateValue.getUTCFullYear(), dateValue.getUTCMonth(), 1));
}

function nextMonth(dateValue) {
  return new Date(Date.UTC(dateValue.getUTCFullYear(), dateValue.getUTCMonth() + 1, 1));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function interpolateColor(start, end, progress) {
  return Math.round(start + (end - start) * progress);
}

function mixRgb(fromColor, toColor, progress) {
  return [
    interpolateColor(fromColor[0], toColor[0], progress),
    interpolateColor(fromColor[1], toColor[1], progress),
    interpolateColor(fromColor[2], toColor[2], progress),
  ];
}

function buildAvailabilityColors(score) {
  const progress = Math.max(0, Math.min(score, 1));
  const lowBackground = [244, 197, 197];
  const midBackground = [241, 214, 133];
  const highBackground = [84, 176, 115];
  const lowBorder = [196, 98, 98];
  const midBorder = [198, 145, 44];
  const highBorder = [44, 115, 72];

  const useHighSegment = progress >= 0.5;
  const segmentProgress = useHighSegment ? (progress - 0.5) / 0.5 : progress / 0.5;
  const background = useHighSegment
    ? mixRgb(midBackground, highBackground, segmentProgress)
    : mixRgb(lowBackground, midBackground, segmentProgress);
  const border = useHighSegment
    ? mixRgb(midBorder, highBorder, segmentProgress)
    : mixRgb(lowBorder, midBorder, segmentProgress);

  return {
    background: `rgb(${background[0]} ${background[1]} ${background[2]} / 0.96)`,
    border: `rgb(${border[0]} ${border[1]} ${border[2]} / 0.86)`,
    ink: progress >= 0.7 ? "#f7fff6" : "#1f2a20",
  };
}

function normalizeVotes(votes) {
  const normalized = {};
  for (const [isoDate, status] of Object.entries(votes ?? {})) {
    normalized[isoDate] = Number(status ?? 0);
  }
  return normalized;
}

function readStoredState(storageKey) {
  if (!storageKey) {
    return null;
  }

  try {
    const rawValue = window.sessionStorage.getItem(storageKey);
    if (!rawValue) {
      return null;
    }
    const parsed = JSON.parse(rawValue);
    return {
      activeStatus: Number(parsed?.activeStatus ?? 2),
      draftVotes: normalizeVotes(parsed?.draftVotes ?? {}),
    };
  } catch (error) {
    return null;
  }
}

function writeStoredState(storageKey, state) {
  if (!storageKey) {
    return;
  }

  try {
    window.sessionStorage.setItem(
      storageKey,
      JSON.stringify({
        activeStatus: Number(state.activeStatus ?? 2),
        draftVotes: state.draftVotes ?? {},
      })
    );
  } catch (error) {
    // Ignore storage write failures.
  }
}

function resolveDraftState(storageKey, savedVotes, defaultActiveStatus) {
  let state = draftStateByKey.get(storageKey);
  if (!state) {
    state = readStoredState(storageKey) ?? {
      activeStatus: Number(defaultActiveStatus ?? 2),
      draftVotes: {},
    };
  }

  if (!Number.isInteger(state.activeStatus) || state.activeStatus < 0 || state.activeStatus > 2) {
    state.activeStatus = Number(defaultActiveStatus ?? 2);
  }

  state.draftVotes = normalizeVotes(state.draftVotes);
  for (const [isoDate, status] of Object.entries(state.draftVotes)) {
    if (!(isoDate in savedVotes) || Number(savedVotes[isoDate] ?? 0) === Number(status)) {
      delete state.draftVotes[isoDate];
    }
  }

  draftStateByKey.set(storageKey, state);
  writeStoredState(storageKey, state);
  return state;
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const monthsContainer = parentElement.querySelector("#calendar-months");
  const subtitleElement = parentElement.querySelector("#calendar-subtitle");
  const tooltipElement = parentElement.querySelector("#calendar-tooltip");
  const shellElement = parentElement.querySelector(".calendar-shell");
  const controlsElement = parentElement.querySelector("#calendar-controls");
  const footerElement = parentElement.querySelector("#calendar-footer");

  monthsContainer.replaceChildren();
  controlsElement.replaceChildren();
  footerElement.replaceChildren();
  tooltipElement.classList.add("is-hidden");

  const locale = data?.locale ?? "fr-FR";
  const themeType = data?.themeType ?? "light";
  const readOnly = Boolean(data?.readOnly);
  const statusOptions = Array.isArray(data?.statusOptions) && data.statusOptions.length
    ? data.statusOptions.map((option) => ({
        value: Number(option.value ?? 0),
        label: String(option.label ?? ""),
        description: String(option.description ?? ""),
      }))
    : [
        { value: 0, label: "Indisponible", description: "Je ne peux pas venir" },
        { value: 1, label: "Peut-etre", description: "Je peux peut-etre, il faut poser un jour" },
        { value: 2, label: "Disponible", description: "Je suis disponible" },
      ];
  const defaultActiveStatus = Number(data?.defaultActiveStatus ?? 2);
  const savedVotes = normalizeVotes(data?.currentVotes ?? {});
  const draftStorageKey = String(data?.draftStorageKey ?? "");
  const state = resolveDraftState(draftStorageKey, savedVotes, defaultActiveStatus);

  shellElement.dataset.theme = themeType;

  const startDate = parseIsoDate(data.startDate);
  const endDate = parseIsoDate(data.endDate);
  const aggregates = data?.aggregates ?? {};

  const weekdayFormatter = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    timeZone: "UTC",
  });
  const monthFormatter = new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  const fullDateFormatter = new Intl.DateTimeFormat(locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  const weekdayLabels = Array.from({ length: 7 }, (_, index) =>
    weekdayFormatter.format(addDays(MONDAY_REFERENCE, index))
  );

  let isDragging = false;
  let draggedDates = new Set();
  const previewCells = new Map();
  const dayButtons = new Map();

  function persistDraftState() {
    draftStateByKey.set(draftStorageKey, state);
    writeStoredState(draftStorageKey, state);
  }

  function currentStatusOption() {
    return (
      statusOptions.find((option) => option.value === Number(state.activeStatus)) ??
      statusOptions[statusOptions.length - 1]
    );
  }

  function updateSubtitle() {
    if (readOnly) {
      subtitleElement.textContent = "Survolez une date pour voir qui est disponible.";
      return;
    }

    const selectedOption = currentStatusOption();
    subtitleElement.textContent =
      `Cliquez ou glissez pour appliquer : ${selectedOption.description}.`;
  }

  function draftCount() {
    return Object.keys(state.draftVotes).length;
  }

  function getEffectiveVote(isoDate) {
    if (Object.prototype.hasOwnProperty.call(state.draftVotes, isoDate)) {
      return Number(state.draftVotes[isoDate]);
    }
    return Number(savedVotes[isoDate] ?? 0);
  }

  function syncDayButton(isoDate) {
    const dayButton = dayButtons.get(isoDate);
    if (!dayButton) {
      return;
    }

    dayButton.classList.remove("my-maybe", "my-available");
    const currentVote = getEffectiveVote(isoDate);
    if (currentVote === 1) {
      dayButton.classList.add("my-maybe");
    } else if (currentVote === 2) {
      dayButton.classList.add("my-available");
    }
  }

  function syncAllDayButtons() {
    for (const isoDate of dayButtons.keys()) {
      syncDayButton(isoDate);
    }
  }

  function renderControls() {
    controlsElement.replaceChildren();
    if (readOnly) {
      return;
    }

    for (const option of statusOptions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "calendar-status-button";
      button.textContent = option.label;
      if (option.value === Number(state.activeStatus)) {
        button.classList.add("is-active");
      }

      button.addEventListener("click", () => {
        state.activeStatus = option.value;
        persistDraftState();
        renderControls();
        updateSubtitle();
      });

      controlsElement.appendChild(button);
    }
  }

  function renderFooter() {
    footerElement.replaceChildren();
    if (readOnly) {
      footerElement.classList.add("is-hidden");
      return;
    }

    footerElement.classList.remove("is-hidden");

    const note = document.createElement("div");
    note.className = "calendar-draft-note";
    const count = draftCount();
    note.textContent = count
      ? `${count} jour(s) en attente. Les couleurs collectives seront mises a jour apres sauvegarde.`
      : "Aucune modification en attente. Les selections restent locales jusqu'a la sauvegarde.";
    footerElement.appendChild(note);

    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.className = "calendar-save-button";
    saveButton.textContent = String(data?.saveButtonLabel ?? "Sauvegarder les choix");
    saveButton.disabled = count === 0;
    saveButton.addEventListener("click", () => {
      const changes = Object.entries(state.draftVotes)
        .sort(([leftDay], [rightDay]) => leftDay.localeCompare(rightDay))
        .map(([isoDate, status]) => ({
          date: isoDate,
          status: Number(status),
        }));

      if (!changes.length) {
        return;
      }

      setTriggerValue("save_batch", { changes });
    });

    footerElement.appendChild(saveButton);
  }

  function clearPreview() {
    for (const cell of previewCells.values()) {
      cell.classList.remove("is-drag-preview");
    }
    previewCells.clear();
  }

  function hideTooltip() {
    tooltipElement.classList.add("is-hidden");
  }

  function showTooltip(cell, isoDate, summary) {
    if (isDragging) {
      return;
    }

    const availableNames = summary.availableNames?.length
      ? summary.availableNames.map(escapeHtml).join(", ")
      : "Personne";
    const maybeNames = summary.maybeNames?.length
      ? summary.maybeNames.map(escapeHtml).join(", ")
      : "Personne";

    tooltipElement.innerHTML = `
      <div class="calendar-tooltip-title">${escapeHtml(fullDateFormatter.format(parseIsoDate(isoDate)))}</div>
      <div class="calendar-tooltip-row">
        <span class="calendar-tooltip-label">Disponibles</span>
        <div class="calendar-tooltip-value">${availableNames}</div>
      </div>
      <div class="calendar-tooltip-row">
        <span class="calendar-tooltip-label">Peut-etre</span>
        <div class="calendar-tooltip-value">${maybeNames}</div>
      </div>
    `;
    tooltipElement.classList.remove("is-hidden");

    const shellRect = shellElement.getBoundingClientRect();
    const cellRect = cell.getBoundingClientRect();
    const tooltipRect = tooltipElement.getBoundingClientRect();

    let left = cellRect.left - shellRect.left + cellRect.width / 2 - tooltipRect.width / 2;
    left = Math.max(8, Math.min(left, shellRect.width - tooltipRect.width - 8));

    let top = cellRect.top - shellRect.top - tooltipRect.height - 10;
    if (top < 8) {
      top = cellRect.bottom - shellRect.top + 10;
    }

    tooltipElement.style.left = `${left}px`;
    tooltipElement.style.top = `${top}px`;
  }

  function registerDraggedCell(isoDate, cell) {
    draggedDates.add(isoDate);
    previewCells.set(isoDate, cell);
    cell.classList.add("is-drag-preview");
  }

  function applyDraftVote(isoDate, status) {
    const targetStatus = Number(status);
    const currentVote = getEffectiveVote(isoDate);
    const nextStatus = currentVote === targetStatus ? 0 : targetStatus;

    if (Number(savedVotes[isoDate] ?? 0) === nextStatus) {
      delete state.draftVotes[isoDate];
    } else {
      state.draftVotes[isoDate] = nextStatus;
    }
    syncDayButton(isoDate);
  }

  function finalizeDrag() {
    if (!isDragging) {
      return;
    }

    const dates = Array.from(draggedDates).sort();
    isDragging = false;
    draggedDates = new Set();
    clearPreview();
    hideTooltip();

    if (!dates.length || readOnly) {
      return;
    }

    for (const isoDate of dates) {
      applyDraftVote(isoDate, state.activeStatus);
    }
    persistDraftState();
    renderFooter();
  }

  const pointerUpHandler = () => finalizeDrag();
  window.addEventListener("pointerup", pointerUpHandler);
  window.addEventListener("pointercancel", pointerUpHandler);

  updateSubtitle();
  renderControls();

  for (
    let cursor = monthStart(startDate);
    cursor.getTime() <= endDate.getTime();
    cursor = nextMonth(cursor)
  ) {
    const monthSection = document.createElement("section");
    monthSection.className = "calendar-month";

    const monthLabel = document.createElement("div");
    monthLabel.className = "calendar-month-label";
    monthLabel.textContent = monthFormatter.format(cursor);
    monthSection.appendChild(monthLabel);

    const weekdayRow = document.createElement("div");
    weekdayRow.className = "calendar-weekdays";
    for (const label of weekdayLabels) {
      const weekdayCell = document.createElement("div");
      weekdayCell.className = "calendar-weekday";
      weekdayCell.textContent = label.replace(".", "");
      weekdayRow.appendChild(weekdayCell);
    }
    monthSection.appendChild(weekdayRow);

    const dayGrid = document.createElement("div");
    dayGrid.className = "calendar-days";

    const firstWeekday = (cursor.getUTCDay() + 6) % 7;
    for (let filler = 0; filler < firstWeekday; filler += 1) {
      const emptyCell = document.createElement("div");
      emptyCell.className = "calendar-empty-cell";
      dayGrid.appendChild(emptyCell);
    }

    const monthLastDay = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + 1, 0));
    for (let dayNumber = 1; dayNumber <= monthLastDay.getUTCDate(); dayNumber += 1) {
      const currentDay = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth(), dayNumber));
      const isoDate = toIsoDate(currentDay);

      if (currentDay.getTime() < startDate.getTime() || currentDay.getTime() > endDate.getTime()) {
        const emptyCell = document.createElement("div");
        emptyCell.className = "calendar-empty-cell";
        dayGrid.appendChild(emptyCell);
        continue;
      }

      const summary = aggregates[isoDate] ?? {
        availableCount: 0,
        maybeCount: 0,
        score: 0,
        availableNames: [],
        maybeNames: [],
      };
      const positiveVotes = Number(summary.availableCount ?? 0) + Number(summary.maybeCount ?? 0);

      const dayButton = document.createElement("button");
      dayButton.type = "button";
      dayButton.className = "calendar-day";
      if (readOnly) {
        dayButton.classList.add("is-readonly");
      }
      if (summary.score > 0) {
        dayButton.classList.add("has-score");
        const colors = buildAvailabilityColors(summary.score);
        dayButton.style.setProperty("--availability-bg", colors.background);
        dayButton.style.setProperty("--availability-border", colors.border);
        dayButton.style.setProperty("--availability-ink", colors.ink);
      }

      const dayNumberElement = document.createElement("div");
      dayNumberElement.className = "calendar-day-number";
      dayNumberElement.textContent = String(dayNumber);
      dayButton.appendChild(dayNumberElement);

      const metaRow = document.createElement("div");
      metaRow.className = "calendar-day-meta";

      const voteCountElement = document.createElement("div");
      voteCountElement.className = "calendar-vote-pill";
      voteCountElement.textContent = positiveVotes > 0 ? String(positiveVotes) : "-";
      metaRow.appendChild(voteCountElement);

      dayButton.appendChild(metaRow);
      dayButtons.set(isoDate, dayButton);
      syncDayButton(isoDate);

      dayButton.addEventListener("pointerdown", (event) => {
        if (readOnly) {
          return;
        }
        if (event.button !== undefined && event.button !== 0) {
          return;
        }
        event.preventDefault();
        isDragging = true;
        draggedDates = new Set();
        clearPreview();
        registerDraggedCell(isoDate, dayButton);
        showTooltip(dayButton, isoDate, summary);
      });

      dayButton.addEventListener("pointerenter", () => {
        if (isDragging) {
          registerDraggedCell(isoDate, dayButton);
          return;
        }
        showTooltip(dayButton, isoDate, summary);
      });

      dayButton.addEventListener("pointerleave", () => {
        if (!isDragging) {
          hideTooltip();
        }
      });

      dayButton.addEventListener("focus", () => showTooltip(dayButton, isoDate, summary));
      dayButton.addEventListener("blur", hideTooltip);

      dayGrid.appendChild(dayButton);
    }

    monthSection.appendChild(dayGrid);
    monthsContainer.appendChild(monthSection);
  }

  syncAllDayButtons();
  renderFooter();

  return () => {
    window.removeEventListener("pointerup", pointerUpHandler);
    window.removeEventListener("pointercancel", pointerUpHandler);
  };
}
