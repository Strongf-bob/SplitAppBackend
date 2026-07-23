export function splitReceipt({ participants, payerId, items }) {
  const participantIds = new Set(participants.map(({ id }) => id));
  if (!participantIds.has(payerId)) {
    throw new Error("Payer must be a receipt participant");
  }

  const shares = Object.fromEntries(participants.map(({ id }) => [id, 0]));
  let total = 0;

  for (const item of items) {
    if (!Number.isInteger(item.amount) || item.amount < 0) {
      throw new Error("Receipt amount must be a non-negative integer");
    }

    const assignedIds = [...new Set(item.participantIds)];
    if (assignedIds.length === 0 || assignedIds.some((id) => !participantIds.has(id))) {
      throw new Error("Every receipt line needs a valid participant");
    }

    total += item.amount;
    const baseShare = Math.floor(item.amount / assignedIds.length);
    let remainder = item.amount % assignedIds.length;

    for (const id of assignedIds) {
      shares[id] += baseShare + (remainder > 0 ? 1 : 0);
      remainder -= remainder > 0 ? 1 : 0;
    }
  }

  const transfers = participants
    .filter(({ id }) => id !== payerId && shares[id] > 0)
    .map(({ id }) => ({ from: id, to: payerId, amount: shares[id] }));

  return { total, shares, transfers };
}

export function formatRubles(amount) {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: amount % 100 === 0 ? 0 : 2,
  }).format(amount / 100);
}

const demoParticipants = [
  { id: "ilya", name: "Илья", shortName: "Илья" },
  { id: "angelina", name: "Ангелина", shortName: "Ангелина" },
  { id: "nastya", name: "Настя", shortName: "Настя" },
];

const demoItems = [
  {
    id: "pizza",
    name: "Пицца",
    amount: 180000,
    participantIds: ["ilya", "angelina", "nastya"],
  },
  {
    id: "pasta",
    name: "Паста",
    amount: 135000,
    participantIds: ["angelina", "nastya"],
  },
  {
    id: "lemonade",
    name: "Лимонад",
    amount: 60000,
    participantIds: ["ilya", "angelina", "nastya"],
  },
  {
    id: "dessert",
    name: "Чизкейк",
    amount: 50000,
    participantIds: ["nastya"],
  },
];
const demoTotal = demoItems.reduce((sum, { amount }) => sum + amount, 0);

function initialAssignments() {
  return Object.fromEntries(
    demoItems.map(({ id, participantIds }) => [id, [...participantIds]]),
  );
}

function renderAssignStep(state) {
  const hasInvalidItem = demoItems.some(({ id }) => state.assignments[id].length === 0);
  const items = demoItems
    .map(({ id, name, amount }) => {
      const selectedIds = state.assignments[id];
      const errorId = `split-demo-${id}-error`;
      const controls = demoParticipants
        .map(
          ({ id: participantId, shortName }) => `
            <button
              class="split-demo-person"
              type="button"
              aria-pressed="${selectedIds.includes(participantId)}"
              data-split-demo-person="${participantId}"
              data-split-demo-item="${id}"
            >
              ${shortName}
            </button>
          `,
        )
        .join("");

      return `
        <li class="split-demo-item" ${selectedIds.length === 0 ? "data-invalid" : ""}>
          <div class="split-demo-item__heading">
            <strong>${name}</strong>
            <span>${formatRubles(amount)}</span>
          </div>
          <div
            class="split-demo-people"
            role="group"
            aria-label="Кто делит позицию ${name}"
            ${selectedIds.length === 0 ? `aria-describedby="${errorId}"` : ""}
          >
            ${controls}
          </div>
          ${
            selectedIds.length === 0
              ? `<p class="split-demo-error" id="${errorId}" role="alert">Выберите хотя бы одного участника</p>`
              : ""
          }
        </li>
      `;
    })
    .join("");

  return `
    <div class="split-demo-intro">
      <h2>Кому что досталось?</h2>
      <p>Ужин после хакатона. За весь чек заплатил Илья.</p>
    </div>
    <div class="split-demo-total">
      <span>Чек целиком</span>
      <strong>${formatRubles(demoTotal)}</strong>
    </div>
    <ul class="split-demo-items">${items}</ul>
    <div class="split-demo-actions">
      <button
        class="split-demo-action split-demo-action--primary"
        type="button"
        data-split-demo-action="review"
        ${hasInvalidItem ? "disabled" : ""}
      >
        Собрать черновик
      </button>
      <button
        class="split-demo-action"
        type="button"
        data-split-demo-action="reset"
      >
        Сбросить
      </button>
    </div>
  `;
}

function renderReviewStep(result) {
  const shares = demoParticipants
    .map(
      ({ id, name }) => `
        <li>
          <span>${name}</span>
          <strong>${formatRubles(result.shares[id])}</strong>
        </li>
      `,
    )
    .join("");

  return `
    <div class="split-demo-intro">
      <h2>Черновик Splitik</h2>
      <p>Проверьте доли до расчёта переводов.</p>
    </div>
    <ul class="split-demo-summary">${shares}</ul>
    <p class="split-demo-note">
      Это локальное демо в браузере. Ничего не сохраняется и финансовых действий не выполняется.
    </p>
    <div class="split-demo-actions">
      <button
        class="split-demo-action split-demo-action--primary"
        type="button"
        data-split-demo-action="confirm"
      >
        Подтвердить черновик
      </button>
      <button
        class="split-demo-action"
        type="button"
        data-split-demo-action="back"
      >
        Изменить
      </button>
    </div>
  `;
}

function renderResultStep(result) {
  const participantNames = Object.fromEntries(
    demoParticipants.map(({ id, name }) => [id, name]),
  );
  const transfers = result.transfers
    .map(
      ({ from, to, amount }) => `
        <li class="split-demo-transfer">
          <span>${participantNames[from]} → ${participantNames[to]}</span>
          <strong>${formatRubles(amount)}</strong>
        </li>
      `,
    )
    .join("");

  return `
    <div class="split-demo-intro">
      <h2>Переводы готовы: ${result.transfers.length}</h2>
      <p>SplitApp свёл позиции к понятному результату.</p>
    </div>
    <ul class="split-demo-transfers">${transfers}</ul>
    <p class="split-demo-note">
      Илья заплатил ${formatRubles(result.total)} и получает только доли остальных участников.
    </p>
    <div class="split-demo-actions">
      <button
        class="split-demo-action split-demo-action--primary"
        type="button"
        data-split-demo-action="edit"
      >
        Изменить распределение
      </button>
      <button
        class="split-demo-action"
        type="button"
        data-split-demo-action="reset"
      >
        Сначала
      </button>
    </div>
  `;
}

function initSplitDemo() {
  const launcher = document.querySelector("[data-split-demo-launcher]");
  const panel = document.querySelector("[data-split-demo-panel]");
  const closeButton = document.querySelector("[data-split-demo-close]");
  const content = document.querySelector("[data-split-demo-content]");
  const progress = document.querySelector("[data-split-demo-progress]");
  const liveRegion = document.querySelector("[data-split-demo-live]");

  if (!launcher || !panel || !closeButton || !content || !progress || !liveRegion) {
    return;
  }

  const mobileQuery = window.matchMedia("(max-width: 700px), (max-height: 620px)");
  const state = {
    step: "assign",
    assignments: initialAssignments(),
  };
  const stepDetails = {
    assign: ["Шаг 1 из 3", 1],
    review: ["Шаг 2 из 3", 2],
    result: ["Шаг 3 из 3", 3],
  };

  function receiptResult() {
    return splitReceipt({
      participants: demoParticipants,
      payerId: "ilya",
      items: demoItems.map(({ id, amount }) => ({
        id,
        amount,
        participantIds: state.assignments[id],
      })),
    });
  }

  function render() {
    const [label] = stepDetails[state.step];
    progress.textContent = label;

    if (state.step === "assign") {
      content.innerHTML = renderAssignStep(state);
      return;
    }

    const result = receiptResult();
    content.innerHTML =
      state.step === "review" ? renderReviewStep(result) : renderResultStep(result);
  }

  function setBackgroundInert(inert) {
    for (const element of document.body.children) {
      if (element === panel || element.tagName === "SCRIPT") continue;
      element.toggleAttribute("inert", inert);
    }
    document.body.toggleAttribute("data-split-demo-mobile-open", inert);
  }

  function syncMobileMode() {
    const open = !panel.hidden;
    panel.setAttribute("role", mobileQuery.matches ? "dialog" : "complementary");
    if (mobileQuery.matches) {
      panel.setAttribute("aria-modal", "true");
    } else {
      panel.removeAttribute("aria-modal");
    }
    setBackgroundInert(open && mobileQuery.matches);
  }

  function openPanel() {
    launcher.hidden = true;
    launcher.setAttribute("aria-expanded", "true");
    panel.hidden = false;
    render();
    syncMobileMode();
    closeButton.focus({ preventScroll: true });
  }

  function closePanel() {
    panel.hidden = true;
    launcher.hidden = false;
    launcher.setAttribute("aria-expanded", "false");
    setBackgroundInert(false);
    launcher.focus({ preventScroll: true });
  }

  launcher.hidden = false;
  render();
  syncMobileMode();

  launcher.addEventListener("click", openPanel);
  closeButton.addEventListener("click", closePanel);
  mobileQuery.addEventListener("change", syncMobileMode);

  content.addEventListener("click", (event) => {
    const personButton = event.target.closest("[data-split-demo-person]");
    if (personButton) {
      const itemId = personButton.dataset.splitDemoItem;
      const participantId = personButton.dataset.splitDemoPerson;
      const selectedIds = state.assignments[itemId];
      state.assignments[itemId] = selectedIds.includes(participantId)
        ? selectedIds.filter((id) => id !== participantId)
        : [
            ...demoParticipants
              .map(({ id }) => id)
              .filter((id) => selectedIds.includes(id) || id === participantId),
          ];
      const item = demoItems.find(({ id }) => id === itemId);
      liveRegion.textContent =
        state.assignments[itemId].length === 0
          ? `Для позиции «${item.name}» выберите хотя бы одного участника.`
          : "";
      render();
      const replacement = [...content.querySelectorAll("[data-split-demo-person]")].find(
        (button) =>
          button.dataset.splitDemoItem === itemId &&
          button.dataset.splitDemoPerson === participantId,
      );
      replacement?.focus();
      return;
    }

    const action = event.target.closest("[data-split-demo-action]")?.dataset
      .splitDemoAction;
    if (!action) return;

    if (action === "review") state.step = "review";
    if (action === "confirm") {
      state.step = "result";
      const { transfers } = receiptResult();
      liveRegion.textContent = `Расчёт готов. Количество переводов: ${transfers.length}.`;
    }
    if (action === "back" || action === "edit") state.step = "assign";
    if (action === "reset") {
      state.step = "assign";
      state.assignments = initialAssignments();
      liveRegion.textContent = "";
    }

    render();
    content.scrollTo({ top: 0, behavior: "instant" });
    content.querySelector("button")?.focus();
  });

  document.addEventListener("keydown", (event) => {
    if (panel.hidden) return;

    if (event.key === "Escape") {
      event.preventDefault();
      closePanel();
      return;
    }

    if (event.key !== "Tab" || !mobileQuery.matches) return;
    const focusable = [
      ...panel.querySelectorAll(
        'button:not(:disabled), [href], input:not(:disabled), [tabindex]:not([tabindex="-1"])',
      ),
    ];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

if (typeof document !== "undefined") {
  initSplitDemo();
}
