#!/usr/bin/env node
//
// The task runner. Every command this project has is named in
// package.json's "cool8" block and run from here.
//
//     npm test              every software suite, in parallel
//     npm test -- --group rtl
//     npm test -- interp asm        just those two
//     npm run check         the encoding tables and the CPU self-test
//     npm run build         boot ROM, basic.bin, BOOT.BIN
//     npm run list          what exists
//
// Node runs nothing of the machine itself; it spawns Python. What it
// buys is the part that was being done by hand in a shell loop: the
// suites run at once instead of one after another, each gets its own
// build directory so they cannot race, output is kept and shown only
// for what failed, and the exit code is the answer.
//
// **Each job gets COOL8_BUILD.** sim/*.py honour it, so thirteen suites
// that all compile basic.bin no longer write it on top of each other.
// Without that, parallel is not merely slower to debug, it is wrong.

import { spawn } from "node:child_process";
import { readFileSync, mkdirSync } from "node:fs";
import { cpus } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const PKG = JSON.parse(readFileSync(path.join(ROOT, "package.json"), "utf8"));
const CFG = PKG.cool8;
const PY = process.env.COOL8_PYTHON || CFG.python || "python";

const GREEN = "\x1b[32m", RED = "\x1b[31m", DIM = "\x1b[2m", OFF = "\x1b[0m";
const ok = (s) => `${GREEN}${s}${OFF}`;
const bad = (s) => `${RED}${s}${OFF}`;
const dim = (s) => `${DIM}${s}${OFF}`;

function jobs(command, argv) {
  if (command === "check") return CFG.check;
  if (command === "build") return CFG.build;
  if (command === "bench") return CFG.bench;

  const gi = argv.indexOf("--group");
  const groups = gi >= 0 ? [argv[gi + 1]] : ["sw"];
  let out = [];
  for (const g of groups) {
    if (!CFG.groups[g]) {
      console.error(`no such group: ${g}. have: ${Object.keys(CFG.groups)}`);
      process.exit(2);
    }
    out = out.concat(CFG.groups[g]);
  }
  const only = argv.filter((a) => !a.startsWith("-") && a !== argv[gi + 1]);
  return only.length ? out.filter((j) => only.includes(j.id)) : out;
}

function run(job) {
  const build = path.join(ROOT, CFG.buildRoot, job.id);
  mkdirSync(build, { recursive: true });
  const started = Date.now();
  return new Promise((resolve) => {
    const p = spawn(PY, [job.run, ...(job.args || [])], {
      cwd: ROOT,
      env: { ...process.env, COOL8_BUILD: build, PYTHONUNBUFFERED: "1" },
    });
    let out = "";
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (out += d));
    p.on("close", (code) => {
      resolve({ job, code, out, ms: Date.now() - started });
    });
    p.on("error", (e) => {
      resolve({ job, code: 127, out: String(e), ms: Date.now() - started });
    });
  });
}

// A suite that prints PASS and exits 0 is a pass. Two of them report a
// count instead, so a zero exit is taken at its word -- but the word
// "FAIL" anywhere in the output is not, whatever the exit code said.
function passed(r) {
  return r.code === 0 && !/\bFAIL\b/.test(r.out);
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--list")) {
    for (const [g, list] of Object.entries(CFG.groups)) {
      console.log(`\n${g}`);
      for (const j of list) console.log(`  ${j.id.padEnd(12)} ${dim(j.about)}`);
    }
    for (const k of ["check", "build", "bench"]) {
      console.log(`\n${k}`);
      for (const j of CFG[k]) console.log(`  ${j.id.padEnd(12)} ${dim(j.about)}`);
    }
    return 0;
  }

  const command = argv[0] || "test";
  const list = jobs(command, argv.slice(1));
  if (!list.length) {
    console.error("nothing to run");
    return 2;
  }

  // Slow jobs first: with a fixed pool the long pole decides the wall
  // clock, and test_run and test_basic are minutes where most are
  // seconds.
  const order = [...list].sort((a, b) => (b.slow ? 1 : 0) - (a.slow ? 1 : 0));
  const limit = Math.max(1, Math.min(order.length, cpus().length));
  console.log(`${command}: ${order.length} job(s), ${limit} at a time\n`);

  const started = Date.now();
  const results = [];
  let next = 0;
  await Promise.all(
    Array.from({ length: limit }, async () => {
      while (next < order.length) {
        const job = order[next++];
        const r = await run(job);
        results.push(r);
        const mark = passed(r) ? ok("PASS") : bad("FAIL");
        console.log(
          `  ${mark}  ${r.job.id.padEnd(12)} ${dim(`${(r.ms / 1000).toFixed(1)}s`)}`
        );
      }
    })
  );

  // A test that passes has nothing to say and its output is noise. A
  // build and a benchmark are the opposite: the numbers *are* the
  // result, and hiding them behind a green PASS makes the command
  // useless for the thing it exists to do.
  const loud = command === "build" || command === "bench";
  if (loud) {
    for (const r of results.sort((a, b) =>
      order.indexOf(a.job) - order.indexOf(b.job)
    )) {
      console.log(`\n${dim("--- " + r.job.id)}`);
      console.log(r.out.trimEnd());
    }
  }

  const failed = results.filter((r) => !passed(r));
  for (const r of failed) {
    if (loud) continue;                     // already printed in full
    console.log(`\n${bad("--- " + r.job.run)} (exit ${r.code})`);
    console.log(r.out.trimEnd().split("\n").slice(-25).join("\n"));
  }

  const secs = ((Date.now() - started) / 1000).toFixed(1);
  console.log(
    `\n${results.length - failed.length}/${results.length} passed in ${secs}s`
  );
  return failed.length ? 1 : 0;
}

main().then((c) => process.exit(c));
