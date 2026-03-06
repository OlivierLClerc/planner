const DAY_IN_MS = 24 * 60 * 60 * 1000;
const MONDAY_REFERENCE = new Date(Date.UTC(2024, 0, 1));

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

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const monthsContainer = parentElement.querySelector("#calendar-months");
  const subtitleElement = parentElement.querySelector("#calendar-subtitle");
  const tooltipElement = parentElement.querySelector("#calendar-tooltip");
  const shellElement = parentElement.querySelector(".calendar-shell");

  monthsContainer.replaceChildren();
  tooltipElement.classList.add("is-hidden");

  const locale = data?.locale ?? "fr-FR";
  const themeType = data?.themeType ?? "light";
  const readOnly = Boolean(data?.readOnly);
  const activeStatusLabel = data?.activeStatusLabel ?? "Disponible";
  shellElement.dataset.theme = themeType;
  subtitleElement.textContent = readOnly
    ? "Survolez une date pour voir qui est disponible."
    : `Cliquez ou glissez pour appliquer le statut actif : ${activeStatusLabel}.`;

  const startDate = parseIsoDate(data.startDate);
  const endDate = parseIsoDate(data.endDate);
  const aggregates = data?.aggregates ?? {};
  const currentVotes = data?.currentVotes ?? {};

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
        <span class="calendar-tooltip-label">Peut-être</span>
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

    setTriggerValue("vote_batch", {
      dates,
      status: data.activeStatus,
    });
  }

  const pointerUpHandler = () => finalizeDrag();
  window.addEventListener("pointerup", pointerUpHandler);
  window.addEventListener("pointercancel", pointerUpHandler);

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
      const currentVote = Number(currentVotes[isoDate] ?? 0);
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
      if (currentVote === 1) {
        dayButton.classList.add("my-maybe");
      }
      if (currentVote === 2) {
        dayButton.classList.add("my-available");
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

  return () => {
    window.removeEventListener("pointerup", pointerUpHandler);
    window.removeEventListener("pointercancel", pointerUpHandler);
  };
}
