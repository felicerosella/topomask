// SPDX-License-Identifier: Apache-2.0
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadCore() {
  const html = fs.readFileSync(path.join(__dirname, "..", "src", "topomask.html"), "utf8");
  const m = html.match(/<script id="core">([\s\S]*?)<\/script>/);
  assert.ok(m, 'missing <script id="core"> in topomask.html');
  const sandbox = { module: { exports: {} } };
  vm.runInNewContext(m[1], sandbox, { filename: "topomask-core.js" });
  return sandbox.module.exports;
}

const core = loadCore();
const { anonymize, restore, mark, newMap } = core;

function run(text, opts = {}) {
  const map = opts.map || newMap();
  const terms = opts.terms === undefined ? "" : opts.terms;
  const res = anonymize(text, map, terms, { keep: opts.keep, enabled: opts.enabled });
  return { map, ...res };
}

function roundTrip(text, opts) {
  const res = run(text, opts);
  assert.equal(restore(res.text, res.map).text, text);
  return res;
}

function assertAbsent(output, values) {
  for (const v of values) assert.ok(!output.toLowerCase().includes(v.toLowerCase()), `"${v}" leaked in: ${output}`);
}

const SAMPLE = [
  "Nov 13 10:02:11 web01 sshd[2211]: Failed password for invalid user jdoe from 192.0.2.10 port 52044 ssh2",
  "Nov 13 10:02:15 web01 sshd[2213]: Accepted publickey for jsmith from 198.51.100.7 port 40112 ssh2",
  "[jdoe@app-ledger-07 ~]# ping -c 3 db-node-12",
  "mount \\\\fileserver01\\share as EXAMPLE\\jdoe",
  "backup job to nas01.corp.example.net (203.0.113.25) completed, owner=jsmith",
  "contact: jane.doe@example.net, ldap: CN=Jane Doe,OU=Operations,DC=corp,DC=example,DC=net",
  "iface eth0 2001:db8::1 ignored, peer fd12:3456:789a:1::25 reachable",
  "",
].join("\n");

test("round trip restores the original text exactly", () => {
  const res = roundTrip(SAMPLE);
  assertAbsent(res.text, [
    "web01",
    "jdoe",
    "jsmith",
    "192.0.2.10",
    "198.51.100.7",
    "203.0.113.25",
    "ledger",
    "fileserver01",
    "nas01",
    "example.net",
    "jane.doe",
    "Jane Doe",
    "Operations",
    "fd12:3456",
  ]);
});

test("documentation IPv6 and loopback are left as they are", () => {
  const res = run("a 2001:db8::1 b ::1 c :: d");
  assert.equal(res.text, "a 2001:db8::1 b ::1 c :: d");
});

test("secrets are removed and never restored", () => {
  const text = [
    "password=Sup3rS3cret!",
    'db: {"api_key": "abcd1234efgh5678"}',
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl",
    "aws AKIAIOSFODNN7EXAMPLE",
    "url https://svc-backup:hunter2pass@repo.example.net/x",
    " username admin secret 5 $1$mERr$hx5rVt7rPNoS4wqbXKX7m0",
    "snmp-server community s3cr3tcomm RO",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW",
    "-----END OPENSSH PRIVATE KEY-----",
    "host key SHA256:nThbg6kXUpJWGl7E1IGOCspRomTxdCARLviKw6E5SY8",
    "card number 4111 1111 1111 1111",
    "<password>xmlsecret</password>",
  ].join("\n");
  const res = run(text);
  assertAbsent(res.text, [
    "Sup3rS3cret",
    "abcd1234efgh5678",
    "eyJhbGci",
    "AKIAIOSFODNN7EXAMPLE",
    "hunter2pass",
    "hx5rVt7rPNoS4wqbXKX7m0",
    "s3cr3tcomm",
    "b3BlbnNzaC1rZXkt",
    "nThbg6kXUpJWGl7E1",
    "4111 1111",
    "xmlsecret",
  ]);
  assert.match(res.text, /<HASH>/);
  assert.match(res.text, /<FINGERPRINT>/);
  assert.match(res.text, /<CARD>/);
  const back = restore(res.text, res.map).text;
  assertAbsent(back, ["Sup3rS3cret", "hunter2pass", "xmlsecret"]);
  assert.ok(res.stats.secret >= 10);
});

test("a card number without a nearby keyword or with a bad checksum stays", () => {
  assert.equal(run("order 4111 1111 1111 1111").text, "order 4111 1111 1111 1111");
  assert.equal(run("card 4111 1111 1111 1112").text, "card 4111 1111 1111 1112");
});

test("pwd pointing to a path is not a secret", () => {
  assert.equal(run("PWD=/var/tmp").text, "PWD=/var/tmp");
});

test("terms: case-insensitive, exact spelling restored, inside hostnames", () => {
  const text = "Contoso ticket for CONTOSO, host contosoweb01 and contoso-db";
  const res = roundTrip(text, { terms: "Contoso=COMPANY_A\n# comment\n" });
  assertAbsent(res.text, ["contoso"]);
  assert.match(res.text, /COMPANY_A ticket for COMPANY_A~1/);
});

test("term fakes inside hostnames are not replaced again", () => {
  const res = roundTrip("ssh contoso-db-02 and hostname=contoso", { terms: "Contoso=COMPANY_A" });
  assert.equal(res.text, "ssh COMPANY_A-db-02 and hostname=COMPANY_A");
});

test("terms without an explicit fake get TERM_N", () => {
  const res = roundTrip("Fabrikam and fabrikam", { terms: "Fabrikam" });
  assert.match(res.text, /^TERM_1 and TERM_1~1$/);
});

test("IPv4: same /24 maps to the same fake network, last octet kept", () => {
  const res = roundTrip("a 192.0.2.10 b 192.0.2.77 c 198.51.100.7");
  const ips = res.text.match(/\d+\.\d+\.\d+\.\d+/g);
  assert.equal(ips.length, 3);
  const net = (ip) => ip.split(".").slice(0, 3).join(".");
  assert.equal(net(ips[0]), net(ips[1]));
  assert.notEqual(net(ips[0]), net(ips[2]));
  assert.equal(ips[0].split(".")[3], "10");
  assert.equal(ips[1].split(".")[3], "77");
  for (const ip of ips) assert.match(ip, /^198\.1[89]\./);
});

test("IPv4: escaped dots in regexes and prefixes", () => {
  const text = "match ^192\\.0\\.2\\.10$ or 192\\.0\\.2\\.\\d+ or '192.0.2.' or 192.0.2.x";
  const res = roundTrip(text);
  assertAbsent(res.text, ["192"]);
  assert.match(res.text, /198\\\.18\\\.0\\\.10/);
});

test("IPv4: special addresses and netmasks are untouched", () => {
  const text = "lo 127.0.0.1 any 0.0.0.0 mcast 239.1.2.3 ll 169.254.10.20 mask 255.255.255.0 wild 128.0.0.0";
  assert.equal(run(text).text, text);
});

test("IPv4: real addresses inside the fake range are not confused with fakes", () => {
  const res = roundTrip("first 192.0.2.1 then 198.18.0.9");
  assert.ok(!res.text.includes("198.18.0.9"));
});

test("IPv4: exhausting the 512 fake networks raises an error, never a CGNAT range", () => {
  const map = newMap();
  const lines = [];
  for (let i = 0; i < 512; i++) lines.push(`10.${i >> 8}.${i & 255}.1`);
  const res = anonymize(lines.join("\n"), map, "", {});
  assert.ok(!/\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(res.text));
  assert.throws(() => anonymize("10.9.9.1", map, "", {}), /fake IPv4 space exhausted/);
});

test("token: a real hostname shaped like a fake is still replaced", () => {
  const res = roundTrip("ssh srv1-x and ping srv1");
  assert.ok(!/\bsrv1\b/.test(res.text.replace(/srv1(?=-)/, "")));
  const map = newMap();
  const first = anonymize("hostname=srv1", map, "", {});
  assert.notEqual(first.text, "hostname=srv1");
});

test("token: no fake is ever assigned to two different values", () => {
  const map = newMap();
  const hosts = [];
  for (let i = 0; i < 3000; i++) hosts.push(`hostname=srv${i} hostname=node${i}`);
  anonymize(hosts.join("\n"), map, "", {});
  const seen = new Map();
  for (const [fake, real] of Object.entries(map.rev)) {
    assert.ok(!seen.has(fake), `fake ${fake} reused`);
    seen.set(fake, real);
  }
  const reals = Object.values(map.fwd.srv);
  assert.equal(new Set(reals).size, reals.length);
});

test("MAC: vendor OUI kept, separator and Cisco format kept", () => {
  const text = "a 00:1A:2B:3C:4D:5E b 00-1a-2b-99-88-77 c 001a.2b3c.4d5e d 00:00:00:00:00:00 e ff:ff:ff:ff:ff:ff";
  const res = roundTrip(text);
  assert.match(res.text, /a 00:1A:2B:00:00:01 /);
  assert.match(res.text, /b 00-1a-2b-00-00-02 /);
  assert.match(res.text, /c 001a\.2b00\.0001 /);
  assert.match(res.text, /00:00:00:00:00:00 e ff:ff:ff:ff:ff:ff$/);
});

test("SID keeps the RID; GUID is replaced", () => {
  const text = "sid S-1-5-21-3623811015-3361044348-30300820-1013 guid 6F9619FF-8B86-D011-B42D-00C04FC964FF";
  const res = roundTrip(text);
  assert.match(res.text, /S-1-5-21-1000-1000-1001-1013/);
  assert.match(res.text, /00000000-0000-0000-0000-000000000001/);
});

test("LDAP: DC= becomes a fake zone, standard containers stay", () => {
  const text = "CN=jdoe,CN=Users,OU=Finance,DC=example,DC=net";
  const res = roundTrip(text);
  assert.match(res.text, /CN=cn1,CN=Users,OU=ou1,DC=dom1,DC=invalid/);
});

test("Italian personal data with a valid checksum is replaced", () => {
  const text = [
    "IBAN IT60 X054 2811 1010 0000 0123 456",
    "IBAN IT60X0542811101000000123456",
    "codice fiscale RSSMRA85T10A562S",
    "P.IVA 01234567897",
    "vat IT01234567897",
    "tel: +39 02 1234 5678",
    "cell 333 123 4567",
  ].join("\n");
  const res = roundTrip(text);
  assertAbsent(res.text, ["X054", "RSSMRA85T10A562S", "01234567897", "1234 5678", "123 4567"]);
  assert.match(res.text, /IBAN_1/);
  assert.match(res.text, /TAXID_1/);
  assert.match(res.text, /VAT_\d/);
  assert.match(res.text, /PHONE_\d/);
});

test("Italian personal data with a wrong checksum stays", () => {
  const text = "IBAN IT61X0542811101000000123456 cf RSSMRA85T10A562X P.IVA 01234567890";
  assert.equal(run(text).text, text);
});

test("keep list: domain and subdomains untouched", () => {
  const text = "fetch https://www.example.net/a and mirror.example.net, not shop.example.test";
  const res = roundTrip(text, { keep: "example.net" });
  assert.match(res.text, /www\.example\.net/);
  assert.match(res.text, /mirror\.example\.net/);
  assert.ok(!res.text.includes("shop.example.test"));
});

test("syslog headers: the host field is replaced", () => {
  const text = "Nov  3 10:02:11 web01 kernel: x\n2026-11-13T10:02:11.123+01:00 db02.example.net systemd[1]: y";
  const res = roundTrip(text);
  assertAbsent(res.text, ["web01", "db02", "example.net"]);
});

test("hostnames with dashes are replaced piece by piece", () => {
  const res = roundTrip("hostname: abcxyz-5911-qwer");
  assert.equal(res.text, "hostname: part1-5911-part2");
});

test("file names are not mistaken for domains", () => {
  const text = "run deploy.sh, edit README.md and setup.py, load libssl.so";
  assert.equal(run(text).text, text);
});

test("anonymizing an already anonymized output changes nothing", () => {
  const map = newMap();
  const first = anonymize(SAMPLE, map, "Contoso", {});
  const before = JSON.stringify(map);
  const second = anonymize(first.text, map, "Contoso", {});
  assert.equal(second.text, first.text);
  assert.equal(JSON.stringify(map), before);
});

test("known names are replaced where they appear on their own", () => {
  const res = roundTrip("hostname=nas01\nlater nas01 reboot; user=jdoe logged as jdoe");
  assertAbsent(res.text, ["nas01", "jdoe"]);
});

test("banners are removed", () => {
  const text = "#################\n#  ~~~~~~~~~~~ #\n#################\nlogin ok\n";
  const res = run(text);
  assert.equal(res.text, "[banner removed]\nlogin ok\n");
});

test("disabled categories are left alone", () => {
  const text = "192.0.2.1 web01.example.net";
  const res = run(text, { enabled: { ip: false } });
  assert.match(res.text, /^192\.0\.2\.1 /);
  assert.ok(!res.text.includes("example.net"));
});

test("mark splits output into plain and replaced segments", () => {
  const res = run("password=x1y2z3w4 at 192.0.2.5 on web01.example.net");
  const segs = mark(res.text, res.map);
  assert.equal(segs.map((s) => s.text).join(""), res.text);
  const reals = segs.filter((s) => s.kind === "fake").map((s) => s.real);
  assert.ok(reals.includes("192.0.2.5"));
  assert.ok(reals.includes("example.net"));
  assert.ok(segs.some((s) => s.kind === "secret"));
});

test("an unsupported map is rejected", () => {
  assert.throws(() => restore("x", { v: 2 }), /unsupported map format/);
});

test("a term named __proto__ does not pollute prototypes", () => {
  const res = roundTrip("value __proto__ here", { terms: "__proto__" });
  assert.equal({}.polluted, undefined);
  assert.match(res.text, /TERM_1/);
});
