import test from "node:test";
import assert from "node:assert/strict";

import { splitReceipt } from "../app/static/landing/assets/split-demo.mjs";

const participants = [
  { id: "ilya", name: "Илья" },
  { id: "angelina", name: "Ангелина" },
  { id: "nastya", name: "Настя" },
];

test("splits the fixed dinner scenario into exact transfers", () => {
  const result = splitReceipt({
    participants,
    payerId: "ilya",
    items: [
      { id: "pizza", amount: 180000, participantIds: ["ilya", "angelina", "nastya"] },
      { id: "pasta", amount: 135000, participantIds: ["angelina", "nastya"] },
      { id: "lemonade", amount: 60000, participantIds: ["ilya", "angelina", "nastya"] },
      { id: "dessert", amount: 50000, participantIds: ["nastya"] },
    ],
  });

  assert.equal(result.total, 425000);
  assert.deepEqual(result.shares, {
    ilya: 80000,
    angelina: 147500,
    nastya: 197500,
  });
  assert.deepEqual(result.transfers, [
    { from: "angelina", to: "ilya", amount: 147500 },
    { from: "nastya", to: "ilya", amount: 197500 },
  ]);
});

test("preserves every kopeck when a line does not divide evenly", () => {
  const result = splitReceipt({
    participants,
    payerId: "ilya",
    items: [{ id: "test", amount: 100, participantIds: ["ilya", "angelina", "nastya"] }],
  });

  assert.equal(Object.values(result.shares).reduce((sum, amount) => sum + amount, 0), 100);
  assert.deepEqual(result.shares, { ilya: 34, angelina: 33, nastya: 33 });
});

test("rejects receipt lines without participants", () => {
  assert.throws(
    () =>
      splitReceipt({
        participants,
        payerId: "ilya",
        items: [{ id: "pizza", amount: 180000, participantIds: [] }],
      }),
    /participant/i,
  );
});
