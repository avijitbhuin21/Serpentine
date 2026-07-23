// Serpentine runtime prelude — emitted at the top of every generated program.
// Provides CPython-parity semantics: floor division, overflow traps, error
// messages (SPEC.md section 11), repr rules, and an insertion-ordered dict.
// Phase 2: fatal runtime errors are ERROR VALUES (SerpErr), not aborts, so
// try/except can catch them (DECISIONS.md D1).
#![allow(dead_code, unused_mut, unused_variables, unused_imports, non_snake_case, unused_parens, non_camel_case_types, unreachable_code, unused_labels, private_interfaces, static_mut_refs, unsafe_op_in_unsafe_fn)]

use std::process;
use std::cell::RefCell;
use std::rc::Rc;

// ---------- the error value ----------

#[derive(Clone, Debug)]
struct SerpErr {
    kind: String,
    msg: String,
}

impl SerpErr {
    fn new(kind: &str, msg: String) -> SerpErr {
        SerpErr { kind: kind.to_string(), msg }
    }
    fn display(&self) -> String {
        if self.msg.is_empty() { self.kind.clone() } else { format!("{}: {}", self.kind, self.msg) }
    }
    fn matches(&self, class: &str) -> bool {
        if class == "Exception" { return true; }
        if class == "OSError" && self.kind == "FileNotFoundError" { return true; }
        if class == "ArithmeticError" && (self.kind == "ZeroDivisionError" || self.kind == "OverflowError") { return true; }
        if class == "LookupError" && (self.kind == "IndexError" || self.kind == "KeyError") { return true; }
        if class == "ValueError" && self.kind == "UnicodeDecodeError" { return true; }
        if class == "RuntimeError" && self.kind == "NotImplementedError" { return true; }
        self.kind == class
    }
}

type SRes<T> = Result<T, SerpErr>;

// ---------- strings (SPEC section 3.7: O(1) copies + SSO) ----------
// Small-string optimization: strings up to 22 bytes live inline (no allocation —
// covers split() parts, chars, keys); longer strings are Rc<str> (O(1) clones).

#[derive(Clone)]
enum SStr {
    Small { len: u8, buf: [u8; 22] },
    Big(Rc<str>),
}

impl SStr {
    fn from_str_slice(s: &str) -> SStr {
        if s.len() <= 22 {
            let mut buf = [0u8; 22];
            buf[..s.len()].copy_from_slice(s.as_bytes());
            SStr::Small { len: s.len() as u8, buf }
        } else {
            SStr::Big(Rc::from(s))
        }
    }
    fn as_str(&self) -> &str {
        match self {
            SStr::Small { len, buf } => unsafe {
                std::str::from_utf8_unchecked(&buf[..*len as usize])
            },
            SStr::Big(r) => r,
        }
    }
}

impl std::fmt::Display for SStr {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

impl std::ops::Deref for SStr {
    type Target = str;
    fn deref(&self) -> &str { self.as_str() }
}
impl PartialEq for SStr {
    fn eq(&self, other: &SStr) -> bool { self.as_str() == other.as_str() }
}
impl PartialOrd for SStr {
    fn partial_cmp(&self, other: &SStr) -> Option<std::cmp::Ordering> {
        self.as_str().partial_cmp(other.as_str())
    }
}

fn sstr(s: &str) -> SStr { SStr::from_str_slice(s) }
fn sstring(s: String) -> SStr { SStr::from_str_slice(&s) }

fn serp_err<T>(kind: &str, msg: String) -> SRes<T> {
    Err(SerpErr::new(kind, msg))
}

fn serp_abort(e: SerpErr) -> ! {
    eprintln!("{}", e.display());
    process::exit(1);
}

// ---------- integer arithmetic with CPython semantics ----------

const OVERFLOW_MSG: &str = "Serpentine int operation overflowed 64 bits";

fn serp_add_i(a: i64, b: i64) -> SRes<i64> {
    a.checked_add(b).ok_or_else(|| SerpErr::new("OverflowError", OVERFLOW_MSG.into()))
}
fn serp_sub_i(a: i64, b: i64) -> SRes<i64> {
    a.checked_sub(b).ok_or_else(|| SerpErr::new("OverflowError", OVERFLOW_MSG.into()))
}
fn serp_mul_i(a: i64, b: i64) -> SRes<i64> {
    a.checked_mul(b).ok_or_else(|| SerpErr::new("OverflowError", OVERFLOW_MSG.into()))
}
fn serp_neg_i(a: i64) -> SRes<i64> {
    a.checked_neg().ok_or_else(|| SerpErr::new("OverflowError", OVERFLOW_MSG.into()))
}
fn serp_floordiv_i(a: i64, b: i64) -> SRes<i64> {
    if b == 0 { return serp_err("ZeroDivisionError", "integer division or modulo by zero".into()); }
    let q = a.checked_div(b).ok_or_else(|| SerpErr::new("OverflowError", OVERFLOW_MSG.into()))?;
    Ok(if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q })
}
fn serp_mod_i(a: i64, b: i64) -> SRes<i64> {
    if b == 0 { return serp_err("ZeroDivisionError", "integer division or modulo by zero".into()); }
    let r = a % b;
    Ok(if r != 0 && ((r < 0) != (b < 0)) { r + b } else { r })
}
fn serp_div_i(a: i64, b: i64) -> SRes<f64> {
    if b == 0 { return serp_err("ZeroDivisionError", "division by zero".into()); }
    Ok((a as f64) / (b as f64))
}
fn serp_pow_i(a: i64, b: i64) -> SRes<i64> {
    if b < 0 { return serp_err("OverflowError", "Serpentine Tier-0 int ** requires a non-negative exponent".into()); }
    let mut result: i64 = 1;
    let mut base = a;
    let mut exp = b;
    while exp > 0 {
        if exp & 1 == 1 { result = serp_mul_i(result, base)?; }
        exp >>= 1;
        if exp > 0 { base = serp_mul_i(base, base)?; }
    }
    Ok(result)
}
fn serp_abs_i(a: i64) -> SRes<i64> {
    a.checked_abs().ok_or_else(|| SerpErr::new("OverflowError", OVERFLOW_MSG.into()))
}

// ---------- float arithmetic with CPython semantics ----------

fn serp_div_f(a: f64, b: f64) -> SRes<f64> {
    if b == 0.0 { return serp_err("ZeroDivisionError", "float division by zero".into()); }
    Ok(a / b)
}
fn serp_floordiv_f(a: f64, b: f64) -> SRes<f64> {
    if b == 0.0 { return serp_err("ZeroDivisionError", "float floor division".into()); }
    Ok((a / b).floor())
}
fn serp_mod_f(a: f64, b: f64) -> SRes<f64> {
    if b == 0.0 { return serp_err("ZeroDivisionError", "float modulo".into()); }
    let r = a % b;
    Ok(if r != 0.0 && ((r < 0.0) != (b < 0.0)) { r + b } else { r })
}

// ---------- repr / str with CPython parity ----------

fn py_float_repr(f: f64) -> String {
    if f.is_nan() { return "nan".to_string(); }
    if f.is_infinite() { return if f > 0.0 { "inf".into() } else { "-inf".into() }; }
    let s = format!("{:?}", f);
    if let Some(epos) = s.find('e') {
        let (mant, exp) = s.split_at(epos);
        let exp = &exp[1..];
        let (sign, digits) = if let Some(stripped) = exp.strip_prefix('-') {
            ("-", stripped)
        } else {
            ("+", exp)
        };
        let digits = if digits.len() < 2 { format!("0{}", digits) } else { digits.to_string() };
        let mant = mant.trim_end_matches(".0");
        return format!("{}e{}{}", mant, sign, digits);
    }
    s
}

trait PyShow {
    fn py_str(&self) -> String;
    fn py_repr(&self) -> String;
}

impl PyShow for i64 {
    fn py_str(&self) -> String { self.to_string() }
    fn py_repr(&self) -> String { self.to_string() }
}
impl PyShow for f64 {
    fn py_str(&self) -> String { py_float_repr(*self) }
    fn py_repr(&self) -> String { py_float_repr(*self) }
}
impl PyShow for bool {
    fn py_str(&self) -> String { if *self { "True".into() } else { "False".into() } }
    fn py_repr(&self) -> String { self.py_str() }
}
impl PyShow for str {
    fn py_str(&self) -> String { self.to_string() }
    fn py_repr(&self) -> String {
        let quote = if self.contains('\'') && !self.contains('"') { '"' } else { '\'' };
        let mut out = String::new();
        out.push(quote);
        for c in self.chars() {
            match c {
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                c if c == quote => { out.push('\\'); out.push(c); }
                c => out.push(c),
            }
        }
        out.push(quote);
        out
    }
}
impl PyShow for String {
    fn py_str(&self) -> String { self.clone() }
    fn py_repr(&self) -> String { self.as_str().py_repr() }
}
impl PyShow for SStr {
    fn py_str(&self) -> String { self.as_str().to_string() }
    fn py_repr(&self) -> String { self.as_str().py_repr() }
}
impl PyShow for SerpErr {
    fn py_str(&self) -> String { self.msg.clone() }
    fn py_repr(&self) -> String { format!("{}({})", self.kind, self.msg.py_repr()) }
}
impl<T: PyShow> PyShow for Vec<T> {
    fn py_str(&self) -> String { self.py_repr() }
    fn py_repr(&self) -> String {
        let parts: Vec<String> = self.iter().map(|x| x.py_repr()).collect();
        format!("[{}]", parts.join(", "))
    }
}
impl<T: PyShow> PyShow for Option<T> {
    fn py_str(&self) -> String {
        match self { Some(v) => v.py_str(), None => "None".into() }
    }
    fn py_repr(&self) -> String {
        match self { Some(v) => v.py_repr(), None => "None".into() }
    }
}
impl<A: PyShow, B: PyShow> PyShow for (A, B) {
    fn py_str(&self) -> String { self.py_repr() }
    fn py_repr(&self) -> String { format!("({}, {})", self.0.py_repr(), self.1.py_repr()) }
}
impl<A: PyShow, B: PyShow, C: PyShow> PyShow for (A, B, C) {
    fn py_str(&self) -> String { self.py_repr() }
    fn py_repr(&self) -> String {
        format!("({}, {}, {})", self.0.py_repr(), self.1.py_repr(), self.2.py_repr())
    }
}
impl<'a, T: PyShow + ?Sized> PyShow for &'a T {
    fn py_str(&self) -> String { (**self).py_str() }
    fn py_repr(&self) -> String { (**self).py_repr() }
}
impl<T: PyShow> PyShow for Rc<RefCell<T>> {
    fn py_str(&self) -> String { self.borrow().py_str() }
    fn py_repr(&self) -> String { self.borrow().py_repr() }
}
impl<T> PyShow for std::rc::Weak<RefCell<T>> {
    // Divergence: CPython (shim = identity) would show the referent here.
    fn py_str(&self) -> String { "<weak>".to_string() }
    fn py_repr(&self) -> String { "<weak>".to_string() }
}

fn py_str<T: PyShow>(v: T) -> String { v.py_str() }
fn py_repr<T: PyShow>(v: T) -> String { v.py_repr() }

// ---------- Shared[T] / Weak[T] (DECISIONS.md D3: Rc, cycles leak) ----------

fn serp_share<T>(v: T) -> Rc<RefCell<T>> { Rc::new(RefCell::new(v)) }

fn serp_downgrade<T>(s: &Rc<RefCell<T>>) -> std::rc::Weak<RefCell<T>> { Rc::downgrade(s) }

fn serp_upgrade<T>(w: &std::rc::Weak<RefCell<T>>) -> Option<Rc<RefCell<T>>> { w.upgrade() }

fn shared_ref<T>(s: &Rc<RefCell<T>>) -> SRes<std::cell::Ref<'_, T>> {
    s.try_borrow().map_err(|_| SerpErr::new("RuntimeError",
        "Shared value is already mutably borrowed".into()))
}
fn shared_mut<T>(s: &Rc<RefCell<T>>) -> SRes<std::cell::RefMut<'_, T>> {
    s.try_borrow_mut().map_err(|_| SerpErr::new("RuntimeError",
        "Shared value is already borrowed".into()))
}

// ---------- list operations with CPython error parity ----------

fn serp_norm_idx(i: i64, len: usize, kind: &str, msg: &str) -> SRes<usize> {
    let n = len as i64;
    let j = if i < 0 { i + n } else { i };
    if j < 0 || j >= n { return serp_err(kind, msg.into()); }
    Ok(j as usize)
}
fn serp_idx<T>(v: &Vec<T>, i: i64) -> SRes<&T> {
    Ok(&v[serp_norm_idx(i, v.len(), "IndexError", "list index out of range")?])
}
fn serp_idx_mut<T>(v: &mut Vec<T>, i: i64) -> SRes<&mut T> {
    let len = v.len();
    Ok(&mut v[serp_norm_idx(i, len, "IndexError", "list index out of range")?])
}
fn serp_idx_set<T>(v: &mut Vec<T>, i: i64, val: T) -> SRes<()> {
    let len = v.len();
    let j = serp_norm_idx(i, len, "IndexError", "list assignment index out of range")?;
    v[j] = val;
    Ok(())
}
fn serp_pop<T>(v: &mut Vec<T>) -> SRes<T> {
    v.pop().ok_or_else(|| SerpErr::new("IndexError", "pop from empty list".into()))
}
fn serp_pop_at<T>(v: &mut Vec<T>, i: i64) -> SRes<T> {
    if v.is_empty() { return serp_err("IndexError", "pop from empty list".into()); }
    let j = serp_norm_idx(i, v.len(), "IndexError", "pop index out of range")?;
    Ok(v.remove(j))
}
fn serp_insert<T>(v: &mut Vec<T>, i: i64, val: T) {
    let n = v.len() as i64;
    let mut j = if i < 0 { i + n } else { i };
    if j < 0 { j = 0; }
    if j > n { j = n; }
    v.insert(j as usize, val);
}
fn serp_sort_f(v: &mut Vec<f64>) {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
}

fn serp_sum_i(v: &Vec<i64>) -> SRes<i64> {
    let mut acc: i64 = 0;
    for x in v { acc = serp_add_i(acc, *x)?; }
    Ok(acc)
}
fn serp_sum_f(v: &Vec<f64>) -> SRes<f64> {
    let mut acc: f64 = 0.0;
    for x in v { acc += *x; }
    Ok(acc)
}
fn serp_min_list<T: PartialOrd + Clone>(v: &Vec<T>, name: &str) -> SRes<T> {
    if v.is_empty() { return serp_err("ValueError", format!("{}() iterable argument is empty", name)); }
    let mut best = v[0].clone();
    for x in &v[1..] { if *x < best { best = x.clone(); } }
    Ok(best)
}
fn serp_max_list<T: PartialOrd + Clone>(v: &Vec<T>, name: &str) -> SRes<T> {
    if v.is_empty() { return serp_err("ValueError", format!("{}() iterable argument is empty", name)); }
    let mut best = v[0].clone();
    for x in &v[1..] { if *x > best { best = x.clone(); } }
    Ok(best)
}
fn serp_min2<T: PartialOrd>(a: T, b: T) -> T { if b < a { b } else { a } }
fn serp_max2<T: PartialOrd>(a: T, b: T) -> T { if b > a { b } else { a } }

struct SerpRange { i: i64, stop: i64, step: i64 }

impl Iterator for SerpRange {
    type Item = i64;
    fn next(&mut self) -> Option<i64> {
        if (self.step > 0 && self.i < self.stop) || (self.step < 0 && self.i > self.stop) {
            let v = self.i;
            self.i += self.step;
            Some(v)
        } else {
            None
        }
    }
}

fn serp_range(start: i64, stop: i64, step: i64) -> SRes<SerpRange> {
    if step == 0 { return serp_err("ValueError", "range() arg 3 must not be zero".into()); }
    Ok(SerpRange { i: start, stop, step })
}

// ---------- insertion-ordered dict (SPEC.md D8) ----------

#[derive(Clone)]
struct SerpDict<K, V> {
    entries: Vec<(K, V)>,
}

impl<K: PartialEq + Clone + PyShow, V> SerpDict<K, V> {
    fn new() -> Self { SerpDict { entries: Vec::new() } }
    fn set(&mut self, k: K, v: V) {
        for e in self.entries.iter_mut() {
            if e.0 == k { e.1 = v; return; }
        }
        self.entries.push((k, v));
    }
    fn get_ref(&self, k: &K) -> SRes<&V> {
        for e in &self.entries {
            if &e.0 == k { return Ok(&e.1); }
        }
        serp_err("KeyError", k.py_repr())
    }
    fn get_mut(&mut self, k: &K) -> SRes<&mut V> {
        for e in self.entries.iter_mut() {
            if &e.0 == k { return Ok(&mut e.1); }
        }
        serp_err("KeyError", k.py_repr())
    }
    fn contains(&self, k: &K) -> bool {
        self.entries.iter().any(|e| &e.0 == k)
    }
    fn pop_key(&mut self, k: &K) -> SRes<V> {
        for (i, e) in self.entries.iter().enumerate() {
            if &e.0 == k { return Ok(self.entries.remove(i).1); }
        }
        serp_err("KeyError", k.py_repr())
    }
    fn len_i(&self) -> i64 { self.entries.len() as i64 }
    fn keys_it(&self) -> impl Iterator<Item = &K> { self.entries.iter().map(|e| &e.0) }
    fn values_it(&self) -> impl Iterator<Item = &V> { self.entries.iter().map(|e| &e.1) }
    fn items_it(&self) -> impl Iterator<Item = (&K, &V)> { self.entries.iter().map(|e| (&e.0, &e.1)) }
}

impl<K: PartialEq + Clone + PyShow, V: Clone> SerpDict<K, V> {
    fn get_opt(&self, k: &K) -> Option<V> {
        for e in &self.entries {
            if &e.0 == k { return Some(e.1.clone()); }
        }
        None
    }
}

impl<K: PartialEq + Clone + PyShow, V: PartialEq> PartialEq for SerpDict<K, V> {
    fn eq(&self, other: &Self) -> bool {
        if self.entries.len() != other.entries.len() { return false; }
        self.entries.iter().all(|(k, v)| {
            other.entries.iter().any(|(k2, v2)| k2 == k && v2 == v)
        })
    }
}

impl<K: PyShow, V: PyShow> PyShow for SerpDict<K, V> {
    fn py_str(&self) -> String { self.py_repr() }
    fn py_repr(&self) -> String {
        let parts: Vec<String> = self.entries.iter()
            .map(|(k, v)| format!("{}: {}", k.py_repr(), v.py_repr()))
            .collect();
        format!("{{{}}}", parts.join(", "))
    }
}

// ---------- str operations ----------

fn py_len_str(s: &str) -> i64 {
    if s.is_ascii() { return s.len() as i64; }
    s.chars().count() as i64
}
fn py_split_ws(s: &str) -> Vec<SStr> { s.split_whitespace().map(sstr).collect() }
fn py_split(s: &str, sep: &str) -> SRes<Vec<SStr>> {
    if sep.is_empty() { return serp_err("ValueError", "empty separator".into()); }
    Ok(s.split(sep).map(sstr).collect())
}
fn py_join(sep: &str, v: &Vec<SStr>) -> SStr {
    let parts: Vec<&str> = v.iter().map(|s| s.as_str()).collect();
    sstring(parts.join(sep))
}
fn py_strip(s: &str) -> SStr { sstr(s.trim()) }
fn py_lstrip(s: &str) -> SStr { sstr(s.trim_start()) }
fn py_rstrip(s: &str) -> SStr { sstr(s.trim_end()) }
fn py_upper(s: &str) -> SStr { sstring(s.to_uppercase()) }
fn py_lower(s: &str) -> SStr { sstring(s.to_lowercase()) }
fn py_startswith(s: &str, p: &str) -> bool { s.starts_with(p) }
fn py_endswith(s: &str, p: &str) -> bool { s.ends_with(p) }
fn py_find(s: &str, sub: &str) -> i64 {
    match s.find(sub) {
        Some(byte_idx) => s[..byte_idx].chars().count() as i64,
        None => -1,
    }
}
fn py_replace(s: &str, from: &str, to: &str) -> SStr { sstring(s.replace(from, to)) }
fn py_contains_str(hay: &str, needle: &str) -> bool { hay.contains(needle) }

fn py_chars(s: &str) -> impl Iterator<Item = SStr> + '_ {
    s.chars().map(|c| sstring(c.to_string()))
}
fn py_str_idx(s: &str, i: i64) -> SRes<SStr> {
    if s.is_ascii() {
        let n = s.len() as i64;
        let j = if i < 0 { i + n } else { i };
        if j < 0 || j >= n { return serp_err("IndexError", "string index out of range".into()); }
        return Ok(sstr(&s[j as usize..j as usize + 1]));
    }
    let n = s.chars().count() as i64;
    let j = if i < 0 { i + n } else { i };
    if j < 0 || j >= n { return serp_err("IndexError", "string index out of range".into()); }
    Ok(sstring(s.chars().nth(j as usize).unwrap().to_string()))
}
fn py_str_slice(s: &str, lo: Option<i64>, hi: Option<i64>) -> SStr {
    let n = if s.is_ascii() { s.len() as i64 } else { s.chars().count() as i64 };
    let norm = |v: i64| -> i64 {
        let x = if v < 0 { v + n } else { v };
        x.clamp(0, n)
    };
    let a = norm(lo.unwrap_or(0));
    let b = norm(hi.unwrap_or(n));
    if a >= b { return sstr(""); }
    if s.is_ascii() {
        return sstr(&s[a as usize..b as usize]);
    }
    sstring(s.chars().skip(a as usize).take((b - a) as usize).collect::<String>())
}
fn py_ord(s: &str) -> SRes<i64> {
    let mut it = s.chars();
    match (it.next(), it.next()) {
        (Some(c), None) => Ok(c as i64),
        _ => serp_err("TypeError", format!(
            "ord() expected a character, but string of length {} found", s.chars().count())),
    }
}
fn py_chr(i: i64) -> SRes<SStr> {
    if i < 0 || i >= 0x110000 {
        return serp_err("ValueError", "chr() arg not in range(0x110000)".into());
    }
    match char::from_u32(i as u32) {
        Some(c) => Ok(sstring(c.to_string())),
        None => serp_err("ValueError", "chr() arg not in range(0x110000)".into()),
    }
}

fn round_ties_even_f(x: f64) -> f64 {
    if (x - x.trunc()).abs() == 0.5 { 2.0 * (x / 2.0).round() } else { x.round() }
}
fn py_round0(x: f64) -> SRes<i64> {
    if x.is_nan() { return serp_err("ValueError", "cannot convert float NaN to integer".into()); }
    if x.is_infinite() { return serp_err("OverflowError", "cannot convert float infinity to integer".into()); }
    let r = round_ties_even_f(x);
    if r < (i64::MIN as f64) || r > (i64::MAX as f64) {
        return serp_err("OverflowError", OVERFLOW_MSG.into());
    }
    Ok(r as i64)
}
fn py_round_n(x: f64, n: i64) -> f64 {
    if x.is_nan() || x.is_infinite() { return x; }
    if n >= 0 {
        let p = n.min(400) as usize;
        format!("{:.*}", p, x).parse::<f64>().unwrap_or(x)
    } else {
        let scale = 10f64.powi((-n).min(400) as i32);
        round_ties_even_f(x / scale) * scale
    }
}

fn serp_sorted<T: PartialOrd + Clone>(v: &Vec<T>) -> Vec<T> {
    let mut c = v.clone();
    c.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    c
}

fn serp_next<T: Clone>(it: &mut std::slice::Iter<'_, T>) -> SRes<T> {
    match it.next() {
        Some(v) => Ok(v.clone()),
        None => serp_err("StopIteration", String::new()),
    }
}

// ---------- conversions ----------

fn py_int_from_str(s: &str) -> SRes<i64> {
    let t = s.trim();
    t.parse::<i64>().map_err(|_| SerpErr::new("ValueError",
        format!("invalid literal for int() with base 10: {}", s.to_string().py_repr())))
}
fn py_int_from_f(f: f64) -> SRes<i64> {
    if f.is_nan() { return serp_err("ValueError", "cannot convert float NaN to integer".into()); }
    if f.is_infinite() { return serp_err("OverflowError", "cannot convert float infinity to integer".into()); }
    let t = f.trunc();
    if t < (i64::MIN as f64) || t > (i64::MAX as f64) {
        return serp_err("OverflowError", OVERFLOW_MSG.into());
    }
    Ok(t as i64)
}
fn py_float_from_str(s: &str) -> SRes<f64> {
    let t = s.trim();
    t.parse::<f64>().map_err(|_| SerpErr::new("ValueError",
        format!("could not convert string to float: {}", s.to_string().py_repr())))
}
fn serp_input() -> SRes<SStr> {
    use std::io::BufRead;
    let mut line = String::new();
    let n = std::io::stdin().lock().read_line(&mut line)
        .map_err(|_| SerpErr::new("EOFError", "EOF when reading a line".into()))?;
    if n == 0 { return serp_err("EOFError", "EOF when reading a line".into()); }
    if line.ends_with('\n') { line.pop(); if line.ends_with('\r') { line.pop(); } }
    Ok(sstring(line))
}

// ---------- files (Tier 1: open / read / write / close; drop closes) ----------

struct SerpFile {
    path: String,
    inner: Option<std::fs::File>,
    readable: bool,
    writable: bool,
}

fn serp_open(path: &str, mode: &str) -> SRes<SerpFile> {
    use std::fs::OpenOptions;
    let (read, write, append, create, truncate) = match mode {
        "r" | "rb" => (true, false, false, false, false),
        "w" | "wb" => (false, true, false, true, true),
        "a" | "ab" => (false, true, true, true, false),
        _ => return serp_err("ValueError", format!("invalid mode: {}", mode.to_string().py_repr())),
    };
    let f = OpenOptions::new().read(read).write(write).append(append)
        .create(create).truncate(truncate).open(path)
        .map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => SerpErr::new("FileNotFoundError",
                format!("[Errno 2] No such file or directory: {}", path.to_string().py_repr())),
            std::io::ErrorKind::PermissionDenied => SerpErr::new("PermissionError",
                format!("[Errno 13] Permission denied: {}", path.to_string().py_repr())),
            _ => SerpErr::new("OSError", format!("{}: {}", e, path.to_string().py_repr())),
        })?;
    Ok(SerpFile { path: path.to_string(), inner: Some(f), readable: read, writable: write || append })
}

impl SerpFile {
    fn read_all(&mut self) -> SRes<SStr> {
        use std::io::Read;
        if !self.readable { return serp_err("io.UnsupportedOperation", "not readable".into()); }
        let f = self.inner.as_mut().ok_or_else(|| SerpErr::new("ValueError",
            "I/O operation on closed file.".into()))?;
        let mut s = String::new();
        f.read_to_string(&mut s).map_err(|e| SerpErr::new("OSError", format!("{}", e)))?;
        Ok(sstring(s))
    }
    fn write_str(&mut self, s: &str) -> SRes<i64> {
        use std::io::Write;
        if !self.writable { return serp_err("io.UnsupportedOperation", "not writable".into()); }
        let f = self.inner.as_mut().ok_or_else(|| SerpErr::new("ValueError",
            "I/O operation on closed file.".into()))?;
        f.write_all(s.as_bytes()).map_err(|e| SerpErr::new("OSError", format!("{}", e)))?;
        Ok(s.chars().count() as i64)
    }
    fn close(&mut self) {
        self.inner = None;   // dropping the File closes it
    }
}

// ---------- bytes / bytearray (Tier 2) ----------

#[derive(Clone, PartialEq, Eq)]
struct SBytes { v: Rc<Vec<u8>> }

impl SBytes {
    fn len_i(&self) -> i64 { self.v.len() as i64 }
}

fn sbytes(v: Vec<u8>) -> SBytes { SBytes { v: Rc::new(v) } }

fn bytes_repr(bs: &[u8]) -> String {
    let has_sq = bs.contains(&b'\'');
    let has_dq = bs.contains(&b'"');
    let q: u8 = if has_sq && !has_dq { b'"' } else { b'\'' };
    let mut out = String::from("b");
    out.push(q as char);
    for &b in bs {
        if b == q || b == b'\\' { out.push('\\'); out.push(b as char); }
        else {
            match b {
                9 => out.push_str("\\t"),
                10 => out.push_str("\\n"),
                13 => out.push_str("\\r"),
                0x20..=0x7e => out.push(b as char),
                _ => out.push_str(&format!("\\x{:02x}", b)),
            }
        }
    }
    out.push(q as char);
    out
}

impl PyShow for SBytes {
    fn py_str(&self) -> String { bytes_repr(&self.v) }
    fn py_repr(&self) -> String { bytes_repr(&self.v) }
}

impl PartialOrd for SBytes {
    fn partial_cmp(&self, other: &SBytes) -> Option<std::cmp::Ordering> {
        Some(self.v.as_slice().cmp(other.v.as_slice()))
    }
}

fn pyb_norm_index(i: i64, n: usize) -> SRes<usize> {
    let idx = if i < 0 { i + n as i64 } else { i };
    if idx < 0 || idx >= n as i64 {
        return serp_err("IndexError", "index out of range".into());
    }
    Ok(idx as usize)
}

fn pyb_index(b: &SBytes, i: i64) -> SRes<i64> {
    Ok(b.v[pyb_norm_index(i, b.v.len())?] as i64)
}

fn pyb_slice(b: &SBytes, lo: Option<i64>, hi: Option<i64>) -> SBytes {
    let n = b.v.len() as i64;
    let mut a = lo.unwrap_or(0); if a < 0 { a += n; }
    let mut z = hi.unwrap_or(n); if z < 0 { z += n; }
    let a = a.clamp(0, n) as usize;
    let z = z.clamp(0, n) as usize;
    if a >= z { return sbytes(Vec::new()); }
    sbytes(b.v[a..z].to_vec())
}

fn pyb_concat(a: &SBytes, b: &SBytes) -> SBytes {
    let mut v = Vec::with_capacity(a.v.len() + b.v.len());
    v.extend_from_slice(&a.v); v.extend_from_slice(&b.v);
    sbytes(v)
}

fn pyb_repeat(a: &SBytes, k: i64) -> SBytes {
    if k <= 0 { return sbytes(Vec::new()); }
    let mut v = Vec::with_capacity(a.v.len() * k as usize);
    for _ in 0..k { v.extend_from_slice(&a.v); }
    sbytes(v)
}

fn pyb_find_at(hay: &[u8], needle: &[u8], from: usize) -> i64 {
    if needle.is_empty() { return from as i64; }
    if needle.len() > hay.len() { return -1; }
    for i in from..=(hay.len() - needle.len()) {
        if &hay[i..i + needle.len()] == needle { return i as i64; }
    }
    -1
}

fn pyb_find(a: &SBytes, sub: &SBytes) -> i64 { pyb_find_at(&a.v, &sub.v, 0) }

fn pyb_contains(a: &SBytes, sub: &SBytes) -> bool { pyb_find(a, sub) >= 0 }

fn pyb_count(a: &SBytes, sub: &SBytes) -> i64 {
    if sub.v.is_empty() { return a.v.len() as i64 + 1; }
    let mut n = 0i64; let mut i = 0usize;
    loop {
        let p = pyb_find_at(&a.v, &sub.v, i);
        if p < 0 { break; }
        n += 1; i = p as usize + sub.v.len();
    }
    n
}

fn pyb_startswith(a: &SBytes, p: &SBytes) -> bool { a.v.starts_with(&p.v) }
fn pyb_endswith(a: &SBytes, p: &SBytes) -> bool { a.v.ends_with(&p.v) }

fn pyb_replace(a: &SBytes, from: &SBytes, to: &SBytes) -> SBytes {
    if from.v.is_empty() {
        let mut v = Vec::new();
        for &b in a.v.iter() { v.extend_from_slice(&to.v); v.push(b); }
        v.extend_from_slice(&to.v);
        return sbytes(v);
    }
    let mut v = Vec::new(); let mut i = 0usize;
    loop {
        let p = pyb_find_at(&a.v, &from.v, i);
        if p < 0 { v.extend_from_slice(&a.v[i..]); break; }
        v.extend_from_slice(&a.v[i..p as usize]);
        v.extend_from_slice(&to.v);
        i = p as usize + from.v.len();
    }
    sbytes(v)
}

fn pyb_split(a: &SBytes, sep: &SBytes) -> SRes<Vec<SBytes>> {
    if sep.v.is_empty() { return serp_err("ValueError", "empty separator".into()); }
    let mut out = Vec::new(); let mut i = 0usize;
    loop {
        let p = pyb_find_at(&a.v, &sep.v, i);
        if p < 0 { out.push(sbytes(a.v[i..].to_vec())); break; }
        out.push(sbytes(a.v[i..p as usize].to_vec()));
        i = p as usize + sep.v.len();
    }
    Ok(out)
}

fn pyb_split_ws(a: &SBytes) -> Vec<SBytes> {
    let mut out = Vec::new(); let mut cur: Vec<u8> = Vec::new();
    for &b in a.v.iter() {
        if b == b' ' || b == b'\t' || b == b'\n' || b == b'\r' || b == 0x0b || b == 0x0c {
            if !cur.is_empty() { out.push(sbytes(std::mem::take(&mut cur))); }
        } else { cur.push(b); }
    }
    if !cur.is_empty() { out.push(sbytes(cur)); }
    out
}

fn pyb_join(sep: &SBytes, items: &Vec<SBytes>) -> SBytes {
    let mut v = Vec::new();
    for (i, it) in items.iter().enumerate() {
        if i > 0 { v.extend_from_slice(&sep.v); }
        v.extend_from_slice(&it.v);
    }
    sbytes(v)
}

fn pyb_is_ws(b: u8) -> bool { matches!(b, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c) }

fn pyb_strip(a: &SBytes) -> SBytes {
    let mut lo = 0usize; let mut hi = a.v.len();
    while lo < hi && pyb_is_ws(a.v[lo]) { lo += 1; }
    while hi > lo && pyb_is_ws(a.v[hi - 1]) { hi -= 1; }
    sbytes(a.v[lo..hi].to_vec())
}
fn pyb_lstrip(a: &SBytes) -> SBytes {
    let mut lo = 0usize;
    while lo < a.v.len() && pyb_is_ws(a.v[lo]) { lo += 1; }
    sbytes(a.v[lo..].to_vec())
}
fn pyb_rstrip(a: &SBytes) -> SBytes {
    let mut hi = a.v.len();
    while hi > 0 && pyb_is_ws(a.v[hi - 1]) { hi -= 1; }
    sbytes(a.v[..hi].to_vec())
}

fn pyb_upper(a: &SBytes) -> SBytes { sbytes(a.v.iter().map(|b| b.to_ascii_uppercase()).collect()) }
fn pyb_lower(a: &SBytes) -> SBytes { sbytes(a.v.iter().map(|b| b.to_ascii_lowercase()).collect()) }

fn pyb_hex(a: &SBytes) -> SStr {
    let mut s = String::with_capacity(a.v.len() * 2);
    for &b in a.v.iter() { s.push_str(&format!("{:02x}", b)); }
    sstring(s)
}

fn pyb_fromhex(s: &str) -> SRes<SBytes> {
    let mut v = Vec::new(); let mut hi: Option<u8> = None;
    for (i, c) in s.chars().enumerate() {
        if c == ' ' {
            if hi.is_some() {
                return serp_err("ValueError",
                    format!("non-hexadecimal number found in fromhex() arg at position {}", i));
            }
            continue;
        }
        let d = c.to_digit(16).ok_or_else(|| SerpErr::new("ValueError",
            format!("non-hexadecimal number found in fromhex() arg at position {}", i)))? as u8;
        match hi { None => hi = Some(d), Some(h) => { v.push(h * 16 + d); hi = None; } }
    }
    if hi.is_some() {
        return serp_err("ValueError",
            format!("non-hexadecimal number found in fromhex() arg at position {}", s.chars().count()));
    }
    Ok(sbytes(v))
}

fn pyb_decode(a: &SBytes) -> SRes<SStr> {
    match std::str::from_utf8(&a.v) {
        Ok(s) => Ok(sstring(s.to_string())),
        Err(e) => serp_err("UnicodeDecodeError",
            format!("'utf-8' codec can't decode byte 0x{:02x} in position {}: invalid start byte",
                    a.v[e.valid_up_to()], e.valid_up_to())),
    }
}

fn py_str_encode(s: &str) -> SBytes { sbytes(s.as_bytes().to_vec()) }

fn pyb_from_ints(xs: &Vec<i64>) -> SRes<SBytes> {
    let mut v = Vec::with_capacity(xs.len());
    for &x in xs.iter() {
        if x < 0 || x > 255 { return serp_err("ValueError", "bytes must be in range(0, 256)".into()); }
        v.push(x as u8);
    }
    Ok(sbytes(v))
}

fn pyb_zeros(n: i64) -> SRes<SBytes> {
    if n < 0 { return serp_err("ValueError", "negative count".into()); }
    Ok(sbytes(vec![0u8; n as usize]))
}

#[derive(Clone, PartialEq, Eq)]
struct SByteArray { v: Vec<u8> }

impl PyShow for SByteArray {
    fn py_str(&self) -> String { format!("bytearray({})", bytes_repr(&self.v)) }
    fn py_repr(&self) -> String { format!("bytearray({})", bytes_repr(&self.v)) }
}

impl SByteArray {
    fn as_bytes(&self) -> SBytes { sbytes(self.v.clone()) }
    fn len_i(&self) -> i64 { self.v.len() as i64 }
    fn get(&self, i: i64) -> SRes<i64> { Ok(self.v[pyb_norm_index(i, self.v.len())?] as i64) }
    fn set(&mut self, i: i64, x: i64) -> SRes<()> {
        if x < 0 || x > 255 { return serp_err("ValueError", "byte must be in range(0, 256)".into()); }
        let idx = pyb_norm_index(i, self.v.len())?;
        self.v[idx] = x as u8;
        Ok(())
    }
    fn push_i(&mut self, x: i64) -> SRes<()> {
        if x < 0 || x > 255 { return serp_err("ValueError", "byte must be in range(0, 256)".into()); }
        self.v.push(x as u8);
        Ok(())
    }
    fn extend_bytes(&mut self, other: &SBytes) { self.v.extend_from_slice(&other.v); }
    fn extend_arr(&mut self, other: &SByteArray) { self.v.extend_from_slice(&other.v); }
}

fn pyba_new() -> SByteArray { SByteArray { v: Vec::new() } }
fn pyba_from_bytes(b: &SBytes) -> SByteArray { SByteArray { v: b.v.as_ref().clone() } }
fn pyba_zeros(n: i64) -> SRes<SByteArray> {
    if n < 0 { return serp_err("ValueError", "negative count".into()); }
    Ok(SByteArray { v: vec![0u8; n as usize] })
}
fn pyba_from_ints(xs: &Vec<i64>) -> SRes<SByteArray> {
    Ok(SByteArray { v: pyb_from_ints(xs)?.v.as_ref().clone() })
}
fn pyba_slice(b: &SByteArray, lo: Option<i64>, hi: Option<i64>) -> SByteArray {
    SByteArray { v: pyb_slice(&sbytes(b.v.clone()), lo, hi).v.as_ref().clone() }
}

fn pyb_ints(a: &SBytes) -> Vec<i64> { a.v.iter().map(|&b| b as i64).collect() }
fn pyba_ints(a: &SByteArray) -> Vec<i64> { a.v.iter().map(|&b| b as i64).collect() }

impl SerpFile {
    fn read_all_bytes(&mut self) -> SRes<SBytes> {
        use std::io::Read;
        if !self.readable { return serp_err("io.UnsupportedOperation", "not readable".into()); }
        let f = self.inner.as_mut().ok_or_else(|| SerpErr::new("ValueError",
            "I/O operation on closed file.".into()))?;
        let mut v = Vec::new();
        f.read_to_end(&mut v).map_err(|e| SerpErr::new("OSError", format!("{}", e)))?;
        Ok(sbytes(v))
    }
    fn write_bytes(&mut self, b: &[u8]) -> SRes<i64> {
        use std::io::Write;
        if !self.writable { return serp_err("io.UnsupportedOperation", "not writable".into()); }
        let f = self.inner.as_mut().ok_or_else(|| SerpErr::new("ValueError",
            "I/O operation on closed file.".into()))?;
        f.write_all(b).map_err(|e| SerpErr::new("OSError", format!("{}", e)))?;
        Ok(b.len() as i64)
    }
}

// ---------- sys ----------
fn serp_argv() -> Vec<SStr> {
    std::env::args().map(sstring).collect()
}

// ---------- runtime-backed libraries (rtlib.py: serp_math / serp_random / serp_time) ----------

fn serp_math_sqrt(x: f64) -> SRes<f64> {
    if x < 0.0 { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.sqrt())
}
fn serp_math_sin(x: f64) -> f64 { x.sin() }
fn serp_math_cos(x: f64) -> f64 { x.cos() }
fn serp_math_tan(x: f64) -> f64 { x.tan() }
fn serp_math_log(x: f64) -> SRes<f64> {
    if x <= 0.0 { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.ln())
}
fn serp_math_exp(x: f64) -> SRes<f64> {
    let r = x.exp();
    if r.is_infinite() && x.is_finite() {
        return serp_err("OverflowError", "math range error".into());
    }
    Ok(r)
}
fn serp_math_pow(x: f64, y: f64) -> SRes<f64> {
    if x == 0.0 && y < 0.0 {
        return serp_err("ValueError", "math domain error".into());
    }
    if x < 0.0 && x.is_finite() && y.is_finite() && y.fract() != 0.0 {
        return serp_err("ValueError", "math domain error".into());
    }
    let r = x.powf(y);
    if r.is_infinite() && x.is_finite() && y.is_finite() {
        return serp_err("OverflowError", "math range error".into());
    }
    Ok(r)
}
fn serp_math_floor(x: f64) -> SRes<i64> { py_int_from_f(x.floor()) }
fn serp_math_ceil(x: f64) -> SRes<i64> { py_int_from_f(x.ceil()) }
fn serp_math_isnan(x: f64) -> bool { x.is_nan() }
fn serp_math_isinf(x: f64) -> bool { x.is_infinite() }
fn serp_math_isfinite(x: f64) -> bool { x.is_finite() }

fn serp_math_acos(x: f64) -> SRes<f64> {
    if x.is_nan() { return Ok(x); }
    if !(-1.0..=1.0).contains(&x) { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.acos())
}
fn serp_math_asin(x: f64) -> SRes<f64> {
    if x.is_nan() { return Ok(x); }
    if !(-1.0..=1.0).contains(&x) { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.asin())
}
fn serp_math_atan(x: f64) -> f64 { x.atan() }
fn serp_math_atan2(y: f64, x: f64) -> f64 { y.atan2(x) }
fn serp_math_acosh(x: f64) -> SRes<f64> {
    if x.is_nan() { return Ok(x); }
    if x < 1.0 { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.acosh())
}
fn serp_math_asinh(x: f64) -> f64 { x.asinh() }
fn serp_math_atanh(x: f64) -> SRes<f64> {
    if x.is_nan() { return Ok(x); }
    if x <= -1.0 || x >= 1.0 { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.atanh())
}
fn serp_math_cosh(x: f64) -> SRes<f64> {
    let r = x.cosh();
    if r.is_infinite() && x.is_finite() {
        return serp_err("OverflowError", "math range error".into());
    }
    Ok(r)
}
fn serp_math_sinh(x: f64) -> SRes<f64> {
    let r = x.sinh();
    if r.is_infinite() && x.is_finite() {
        return serp_err("OverflowError", "math range error".into());
    }
    Ok(r)
}
fn serp_math_tanh(x: f64) -> f64 { x.tanh() }
fn serp_math_cbrt(x: f64) -> f64 { x.cbrt() }
fn serp_math_degrees(x: f64) -> f64 { x * (180.0 / std::f64::consts::PI) }
fn serp_math_radians(x: f64) -> f64 { x * (std::f64::consts::PI / 180.0) }
fn serp_math_exp2(x: f64) -> SRes<f64> {
    let r = x.exp2();
    if r.is_infinite() && x.is_finite() {
        return serp_err("OverflowError", "math range error".into());
    }
    Ok(r)
}
fn serp_math_expm1(x: f64) -> SRes<f64> {
    let r = x.exp_m1();
    if r.is_infinite() && x.is_finite() {
        return serp_err("OverflowError", "math range error".into());
    }
    Ok(r)
}
fn serp_math_fabs(x: f64) -> f64 { x.abs() }
fn serp_math_log10(x: f64) -> SRes<f64> {
    if x <= 0.0 { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.log10())
}
fn serp_math_log2(x: f64) -> SRes<f64> {
    if x <= 0.0 { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.log2())
}
fn serp_math_log1p(x: f64) -> SRes<f64> {
    if x <= -1.0 { return serp_err("ValueError", "math domain error".into()); }
    Ok(x.ln_1p())
}
fn serp_math_copysign(x: f64, y: f64) -> f64 { x.copysign(y) }
fn serp_math_fmod(x: f64, y: f64) -> SRes<f64> {
    if x.is_nan() || y.is_nan() { return Ok(f64::NAN); }
    if x.is_infinite() || y == 0.0 {
        return serp_err("ValueError", "math domain error".into());
    }
    Ok(x % y)
}
fn serp_math_ldexp(x: f64, i: i64) -> SRes<f64> {
    if x == 0.0 || !x.is_finite() { return Ok(x); }
    let mut r = x;
    let mut e = i.clamp(-5000, 5000);
    while e > 0 {
        let s = e.min(1000);
        r *= (2.0f64).powi(s as i32);
        e -= s;
    }
    while e < 0 {
        let s = (-e).min(1000);
        r /= (2.0f64).powi(s as i32);
        e += s;
    }
    if r.is_infinite() {
        return serp_err("OverflowError", "math range error".into());
    }
    Ok(r)
}
fn serp_math_trunc(x: f64) -> SRes<i64> { py_int_from_f(x.trunc()) }
fn serp_math_hypot(x: f64, y: f64) -> f64 { x.hypot(y) }
fn serp_next_after(x: f64, y: f64) -> f64 {
    if x.is_nan() || y.is_nan() { return f64::NAN; }
    if x == y { return y; }
    if x == 0.0 {
        return if y > 0.0 { f64::from_bits(1) } else { -f64::from_bits(1) };
    }
    let bits = x.to_bits();
    let next = if (y > x) == (x > 0.0) { bits + 1 } else { bits - 1 };
    f64::from_bits(next)
}
fn serp_math_nextafter(x: f64, y: f64) -> f64 { serp_next_after(x, y) }
fn serp_math_ulp(x: f64) -> f64 {
    if x.is_nan() { return x; }
    let x = x.abs();
    if x.is_infinite() { return x; }
    if x == f64::MAX { return x - serp_next_after(x, f64::NEG_INFINITY); }
    serp_next_after(x, f64::INFINITY) - x
}
fn serp_math_factorial(n: i64) -> SRes<i64> {
    if n < 0 {
        return serp_err("ValueError", "factorial() not defined for negative values".into());
    }
    if n > 20 {
        return serp_err("OverflowError", "factorial() result exceeds the native int width".into());
    }
    let mut r: i64 = 1;
    for i in 2..=n { r *= i; }
    Ok(r)
}
fn serp_math_gcd(a: i64, b: i64) -> SRes<i64> {
    let (mut x, mut y) = ((a as i128).unsigned_abs(), (b as i128).unsigned_abs());
    while y != 0 {
        let t = x % y;
        x = y;
        y = t;
    }
    if x > i64::MAX as u128 {
        return serp_err("OverflowError", "gcd() result exceeds the native int width".into());
    }
    Ok(x as i64)
}
fn serp_math_lcm(a: i64, b: i64) -> SRes<i64> {
    if a == 0 || b == 0 { return Ok(0); }
    let g = match serp_math_gcd(a, b) { Ok(v) => v as i128, Err(e) => return Err(e) };
    let r = ((a as i128) / g * (b as i128)).unsigned_abs();
    if r > i64::MAX as u128 {
        return serp_err("OverflowError", "lcm() result exceeds the native int width".into());
    }
    Ok(r as i64)
}
fn serp_math_isqrt(n: i64) -> SRes<i64> {
    if n < 0 {
        return serp_err("ValueError", "isqrt() argument must be nonnegative".into());
    }
    let mut r = (n as f64).sqrt() as i64;
    while r > 0 && (r as i128) * (r as i128) > n as i128 { r -= 1; }
    while ((r + 1) as i128) * ((r + 1) as i128) <= n as i128 { r += 1; }
    Ok(r)
}
fn serp_math_comb(n: i64, k: i64) -> SRes<i64> {
    if n < 0 { return serp_err("ValueError", "n must be a non-negative integer".into()); }
    if k < 0 { return serp_err("ValueError", "k must be a non-negative integer".into()); }
    if k > n { return Ok(0); }
    let kk = if k > n - k { n - k } else { k };
    let mut r: i128 = 1;
    for i in 1..=kk {
        r = r * ((n - kk + i) as i128) / (i as i128);
        if r > i64::MAX as i128 {
            return serp_err("OverflowError", "comb() result exceeds the native int width".into());
        }
    }
    Ok(r as i64)
}
fn serp_math_perm(n: i64, k: i64) -> SRes<i64> {
    if n < 0 { return serp_err("ValueError", "n must be a non-negative integer".into()); }
    if k < 0 { return serp_err("ValueError", "k must be a non-negative integer".into()); }
    if k > n { return Ok(0); }
    let mut r: i128 = 1;
    for i in 0..k {
        r *= (n - i) as i128;
        if r > i64::MAX as i128 {
            return serp_err("OverflowError", "perm() result exceeds the native int width".into());
        }
    }
    Ok(r as i64)
}
fn serp_frexp_parts(x: f64) -> (f64, i64) {
    if x == 0.0 || x.is_nan() || x.is_infinite() { return (x, 0); }
    let bits = x.to_bits();
    let exp = ((bits >> 52) & 0x7ff) as i64;
    if exp == 0 {
        let (m, e) = serp_frexp_parts(x * 18014398509481984.0);
        return (m, e - 54);
    }
    let e = exp - 1022;
    let m = f64::from_bits((bits & !(0x7ffu64 << 52)) | (1022u64 << 52));
    (m, e)
}
fn serp_math_frexp_m(x: f64) -> f64 { serp_frexp_parts(x).0 }
fn serp_math_frexp_e(x: f64) -> i64 { serp_frexp_parts(x).1 }
fn serp_math_modf_frac(x: f64) -> f64 {
    if x.is_infinite() { return if x > 0.0 { 0.0 } else { -0.0 }; }
    if x.is_nan() { return x; }
    x - x.trunc()
}
fn serp_math_modf_int(x: f64) -> f64 {
    if x.is_infinite() || x.is_nan() { return x; }
    x.trunc()
}

// MT19937 (CPython `random` parity) — seeding and generation are bit-for-bit
// identical to CPython's Mersenne Twister, so the serp-random facade dual-runs
// byte-identically for seeded sequences.
const MT_N: usize = 624;
const MT_M: usize = 397;

thread_local! {
    static SERP_MT: std::cell::RefCell<(Box<[u32; MT_N]>, usize)> =
        std::cell::RefCell::new((Box::new([0u32; MT_N]), MT_N + 1));
    static SERP_MT_SEEDED: std::cell::Cell<bool> = std::cell::Cell::new(false);
}

fn mt_init_genrand(mt: &mut [u32; MT_N], s: u32) {
    mt[0] = s;
    for i in 1..MT_N {
        mt[i] = 1812433253u32
            .wrapping_mul(mt[i - 1] ^ (mt[i - 1] >> 30))
            .wrapping_add(i as u32);
    }
}

fn mt_init_by_array(mt: &mut [u32; MT_N], key: &[u32]) {
    mt_init_genrand(mt, 19650218);
    let (mut i, mut j) = (1usize, 0usize);
    let mut k = if MT_N > key.len() { MT_N } else { key.len() };
    while k > 0 {
        mt[i] = (mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)).wrapping_mul(1664525)))
            .wrapping_add(key[j])
            .wrapping_add(j as u32);
        i += 1;
        j += 1;
        if i >= MT_N {
            mt[0] = mt[MT_N - 1];
            i = 1;
        }
        if j >= key.len() {
            j = 0;
        }
        k -= 1;
    }
    k = MT_N - 1;
    while k > 0 {
        mt[i] = (mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)).wrapping_mul(1566083941)))
            .wrapping_sub(i as u32);
        i += 1;
        if i >= MT_N {
            mt[0] = mt[MT_N - 1];
            i = 1;
        }
        k -= 1;
    }
    mt[0] = 0x80000000;
}

fn mt_genrand(state: &mut (Box<[u32; MT_N]>, usize)) -> u32 {
    let (mt, mti) = (&mut state.0, &mut state.1);
    if *mti >= MT_N {
        for kk in 0..MT_N - MT_M {
            let y = (mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7fffffff);
            mt[kk] = mt[kk + MT_M] ^ (y >> 1) ^ if y & 1 == 1 { 0x9908b0df } else { 0 };
        }
        for kk in MT_N - MT_M..MT_N - 1 {
            let y = (mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7fffffff);
            mt[kk] = mt[kk + MT_M - MT_N] ^ (y >> 1) ^ if y & 1 == 1 { 0x9908b0df } else { 0 };
        }
        let y = (mt[MT_N - 1] & 0x80000000) | (mt[0] & 0x7fffffff);
        mt[MT_N - 1] = mt[MT_M - 1] ^ (y >> 1) ^ if y & 1 == 1 { 0x9908b0df } else { 0 };
        *mti = 0;
    }
    let mut y = mt[*mti];
    *mti += 1;
    y ^= y >> 11;
    y ^= (y << 7) & 0x9d2c5680;
    y ^= (y << 15) & 0xefc60000;
    y ^= y >> 18;
    y
}

fn serp_rand_set_key(key: &[u32]) {
    SERP_MT.with(|c| {
        let mut st = c.borrow_mut();
        mt_init_by_array(&mut st.0, key);
        st.1 = MT_N;
    });
    SERP_MT_SEEDED.with(|c| c.set(true));
}

fn serp_rand_seed(n: i64) {
    // CPython seeds from the absolute value split into little-endian 32-bit limbs.
    let mut v = (n as i128).unsigned_abs();
    let mut key: Vec<u32> = Vec::new();
    while v > 0 {
        key.push((v & 0xffffffff) as u32);
        v >>= 32;
    }
    if key.is_empty() {
        key.push(0);
    }
    serp_rand_set_key(&key);
}

fn serp_rand_seed_sys() {
    let mut buf = [0u8; 32];
    serp_entropy(&mut buf);
    let mut key = [0u32; 8];
    for i in 0..8 {
        key[i] = u32::from_le_bytes([buf[4 * i], buf[4 * i + 1], buf[4 * i + 2], buf[4 * i + 3]]);
    }
    serp_rand_set_key(&key);
}

fn serp_rand_next32() -> u32 {
    if !SERP_MT_SEEDED.with(|c| c.get()) {
        serp_rand_seed_sys();
    }
    SERP_MT.with(|c| mt_genrand(&mut c.borrow_mut()))
}

fn serp_rand_random() -> f64 {
    let a = (serp_rand_next32() >> 5) as f64;
    let b = (serp_rand_next32() >> 6) as f64;
    (a * 67108864.0 + b) * (1.0 / 9007199254740992.0)
}

fn serp_rand_getrandbits(k: i64) -> SRes<i64> {
    if k <= 0 {
        return serp_err("ValueError", "number of bits must be greater than zero".into());
    }
    if k > 63 {
        return serp_err("OverflowError",
                        "getrandbits(k) with k > 63 exceeds the native int width".into());
    }
    let mut left = k as u32;
    let mut result: u64 = 0;
    let mut shift = 0u32;
    while left > 0 {
        let take = if left > 32 { 32 } else { left };
        let r = serp_rand_next32() >> (32 - take);
        result |= (r as u64) << shift;
        shift += 32;
        left -= take;
    }
    Ok(result as i64)
}

fn serp_rand_randbelow(n: i64) -> i64 {
    if n <= 0 {
        return 0;
    }
    let k = (64 - (n as u64).leading_zeros()) as i64;
    loop {
        let r = match serp_rand_getrandbits(k) {
            Ok(v) => v,
            Err(_) => 0,
        };
        if r < n {
            return r;
        }
    }
}

thread_local! {
    static SERP_MONO_START: std::time::Instant = std::time::Instant::now();
}

fn serp_time_time() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64()).unwrap_or(0.0)
}
fn serp_time_monotonic() -> f64 { SERP_MONO_START.with(|s| s.elapsed().as_secs_f64()) }
fn serp_time_time_ns() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as i64).unwrap_or(0)
}
fn serp_time_monotonic_ns() -> i64 {
    SERP_MONO_START.with(|s| s.elapsed().as_nanos() as i64)
}
fn serp_time_perf_counter() -> f64 { serp_time_monotonic() }
fn serp_time_perf_counter_ns() -> i64 { serp_time_monotonic_ns() }
fn serp_time_sleep(secs: f64) -> SRes<()> {
    if secs.is_nan() {
        return serp_err("ValueError", "Invalid value NaN (not a number)".into());
    }
    if secs < 0.0 {
        return serp_err("ValueError", "sleep length must be non-negative".into());
    }
    if secs > 9.0e9 {
        return serp_err("OverflowError", "timeout value is too large".into());
    }
    std::thread::sleep(std::time::Duration::from_secs_f64(secs));
    Ok(())
}

// ---------- rtlib: serp_log (runtime-held logging state — DECISIONS.md D12:
// the process-global logger registry lives in the runtime, like MT19937's
// state; Logger values in Serpentine code stay plain immutable dataclasses) ----------

thread_local! {
    static SERP_LOG_KV: std::cell::RefCell<std::collections::HashMap<String, String>> =
        std::cell::RefCell::new(std::collections::HashMap::new());
}

fn serp_log_set(key: &str, val: &str) {
    SERP_LOG_KV.with(|c| { c.borrow_mut().insert(key.to_string(), val.to_string()); });
}

fn serp_log_get(key: &str) -> SStr {
    SERP_LOG_KV.with(|c| match c.borrow().get(key) {
        Some(v) => sstring(v.clone()),
        None => sstr(""),
    })
}

fn serp_log_write_err(line: &str) {
    eprintln!("{}", line);
}

// ---------- rtlib: serp_os (env + filesystem; error messages are normalized
// identically in the CPython delegate so dual runs stay byte-identical) ----------

fn os_repr(p: &str) -> String { p.to_string().py_repr() }

fn serp_os_getenv(name: &str) -> SStr {
    match std::env::var(name) { Ok(v) => sstring(v), Err(_) => sstr("") }
}

fn serp_os_has_env(name: &str) -> bool {
    std::env::var_os(name).is_some()
}

fn env_name_ok(name: &str) -> bool {
    !name.is_empty() && !name.contains('=') && !name.contains('\0')
}

fn serp_os_setenv(name: &str, value: &str) -> SRes<()> {
    if !env_name_ok(name) {
        return serp_err("ValueError", "illegal environment variable name".into());
    }
    if value.contains('\0') {
        return serp_err("ValueError", "embedded null character".into());
    }
    std::env::set_var(name, value);
    Ok(())
}

fn serp_os_unsetenv(name: &str) -> SRes<()> {
    if !env_name_ok(name) {
        return serp_err("ValueError", "illegal environment variable name".into());
    }
    std::env::remove_var(name);
    Ok(())
}

fn serp_os_getcwd() -> SRes<SStr> {
    match std::env::current_dir() {
        Ok(p) => Ok(sstring(p.to_string_lossy().into_owned())),
        Err(_) => serp_err("OSError", "getcwd failed".into()),
    }
}

fn serp_os_chdir(p: &str) -> SRes<()> {
    match std::env::set_current_dir(p) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound =>
            serp_err("FileNotFoundError", format!("No such file or directory: {}", os_repr(p))),
        Err(_) => serp_err("OSError", format!("Not a directory: {}", os_repr(p))),
    }
}

fn serp_os_exists(p: &str) -> bool { std::path::Path::new(p).exists() }
fn serp_os_is_file(p: &str) -> bool { std::path::Path::new(p).is_file() }
fn serp_os_is_dir(p: &str) -> bool { std::path::Path::new(p).is_dir() }

fn serp_os_mkdir(p: &str) -> SRes<()> {
    match std::fs::create_dir(p) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists =>
            serp_err("OSError", format!("File exists: {}", os_repr(p))),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound =>
            serp_err("FileNotFoundError", format!("No such file or directory: {}", os_repr(p))),
        Err(_) => serp_err("OSError", format!("mkdir failed: {}", os_repr(p))),
    }
}

fn serp_os_rmdir(p: &str) -> SRes<()> {
    match std::fs::remove_dir(p) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound =>
            serp_err("FileNotFoundError", format!("No such file or directory: {}", os_repr(p))),
        Err(_) => serp_err("OSError", format!("Directory not empty: {}", os_repr(p))),
    }
}

fn serp_os_remove(p: &str) -> SRes<()> {
    match std::fs::remove_file(p) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound =>
            serp_err("FileNotFoundError", format!("No such file or directory: {}", os_repr(p))),
        Err(_) => serp_err("OSError", format!("Cannot remove: {}", os_repr(p))),
    }
}

fn serp_os_listdir(p: &str) -> SRes<Vec<SStr>> {
    let rd = match std::fs::read_dir(p) {
        Ok(rd) => rd,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound =>
            return serp_err("FileNotFoundError", format!("No such file or directory: {}", os_repr(p))),
        Err(_) => return serp_err("OSError", format!("Not a directory: {}", os_repr(p))),
    };
    let mut names: Vec<String> = Vec::new();
    for entry in rd {
        match entry {
            Ok(en) => names.push(en.file_name().to_string_lossy().into_owned()),
            Err(_) => return serp_err("OSError", format!("Not a directory: {}", os_repr(p))),
        }
    }
    names.sort();
    Ok(names.into_iter().map(sstring).collect())
}

// ---------- rtlib: serp_hashlib (self-contained digests; no crates) ----------

fn hex_lower(bytes: &[u8]) -> SStr {
    let digits = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(digits[(b >> 4) as usize] as char);
        out.push(digits[(b & 15) as usize] as char);
    }
    sstring(out)
}

const SHA256_K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

fn sha256_digest(data: &[u8]) -> [u8; 32] {
    let mut h: [u32; 8] = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                           0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    let mut msg = data.to_vec();
    let bitlen = (data.len() as u64).wrapping_mul(8);
    msg.push(0x80);
    while msg.len() % 64 != 56 { msg.push(0); }
    msg.extend_from_slice(&bitlen.to_be_bytes());
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([chunk[4 * i], chunk[4 * i + 1],
                                       chunk[4 * i + 2], chunk[4 * i + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d) = (h[0], h[1], h[2], h[3]);
        let (mut e, mut f, mut g, mut hh) = (h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh.wrapping_add(s1).wrapping_add(ch)
                       .wrapping_add(SHA256_K[i]).wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g; g = f; f = e; e = d.wrapping_add(t1);
            d = c; c = b; b = a; a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a); h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c); h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e); h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g); h[7] = h[7].wrapping_add(hh);
    }
    let mut out = [0u8; 32];
    for i in 0..8 { out[4 * i..4 * i + 4].copy_from_slice(&h[i].to_be_bytes()); }
    out
}

fn sha1_digest(data: &[u8]) -> [u8; 20] {
    let mut h: [u32; 5] = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0];
    let mut msg = data.to_vec();
    let bitlen = (data.len() as u64).wrapping_mul(8);
    msg.push(0x80);
    while msg.len() % 64 != 56 { msg.push(0); }
    msg.extend_from_slice(&bitlen.to_be_bytes());
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 80];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([chunk[4 * i], chunk[4 * i + 1],
                                       chunk[4 * i + 2], chunk[4 * i + 3]]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let (mut a, mut b, mut c, mut d, mut e) = (h[0], h[1], h[2], h[3], h[4]);
        for i in 0..80 {
            let (f, k) = if i < 20 {
                ((b & c) | ((!b) & d), 0x5A827999u32)
            } else if i < 40 {
                (b ^ c ^ d, 0x6ED9EBA1)
            } else if i < 60 {
                ((b & c) | (b & d) | (c & d), 0x8F1BBCDC)
            } else {
                (b ^ c ^ d, 0xCA62C1D6)
            };
            let tmp = a.rotate_left(5).wrapping_add(f).wrapping_add(e)
                       .wrapping_add(k).wrapping_add(w[i]);
            e = d; d = c; c = b.rotate_left(30); b = a; a = tmp;
        }
        h[0] = h[0].wrapping_add(a); h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c); h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
    }
    let mut out = [0u8; 20];
    for i in 0..5 { out[4 * i..4 * i + 4].copy_from_slice(&h[i].to_be_bytes()); }
    out
}

const MD5_T: [u32; 64] = [
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
    0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
    0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
    0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
    0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
    0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391,
];

const MD5_S: [u32; 64] = [
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
];

fn md5_digest(data: &[u8]) -> [u8; 16] {
    let (mut a0, mut b0, mut c0, mut d0) =
        (0x67452301u32, 0xefcdab89u32, 0x98badcfeu32, 0x10325476u32);
    let mut msg = data.to_vec();
    let bitlen = (data.len() as u64).wrapping_mul(8);
    msg.push(0x80);
    while msg.len() % 64 != 56 { msg.push(0); }
    msg.extend_from_slice(&bitlen.to_le_bytes());
    for chunk in msg.chunks(64) {
        let mut m = [0u32; 16];
        for i in 0..16 {
            m[i] = u32::from_le_bytes([chunk[4 * i], chunk[4 * i + 1],
                                       chunk[4 * i + 2], chunk[4 * i + 3]]);
        }
        let (mut a, mut b, mut c, mut d) = (a0, b0, c0, d0);
        for i in 0..64 {
            let (f, g) = if i < 16 {
                ((b & c) | ((!b) & d), i)
            } else if i < 32 {
                ((d & b) | ((!d) & c), (5 * i + 1) % 16)
            } else if i < 48 {
                (b ^ c ^ d, (3 * i + 5) % 16)
            } else {
                (c ^ (b | (!d)), (7 * i) % 16)
            };
            let tmp = d;
            d = c;
            c = b;
            let sum = a.wrapping_add(f).wrapping_add(MD5_T[i]).wrapping_add(m[g]);
            b = b.wrapping_add(sum.rotate_left(MD5_S[i]));
            a = tmp;
        }
        a0 = a0.wrapping_add(a); b0 = b0.wrapping_add(b);
        c0 = c0.wrapping_add(c); d0 = d0.wrapping_add(d);
    }
    let mut out = [0u8; 16];
    out[0..4].copy_from_slice(&a0.to_le_bytes());
    out[4..8].copy_from_slice(&b0.to_le_bytes());
    out[8..12].copy_from_slice(&c0.to_le_bytes());
    out[12..16].copy_from_slice(&d0.to_le_bytes());
    out
}

fn serp_hash_sha256(s: &str) -> SStr { hex_lower(&sha256_digest(s.as_bytes())) }
fn serp_hash_sha1(s: &str) -> SStr { hex_lower(&sha1_digest(s.as_bytes())) }
fn serp_hash_md5(s: &str) -> SStr { hex_lower(&md5_digest(s.as_bytes())) }
fn serp_hash_sha256_y(b: &SBytes) -> SStr { hex_lower(&sha256_digest(&b.v)) }
fn serp_hash_sha1_y(b: &SBytes) -> SStr { hex_lower(&sha1_digest(&b.v)) }
fn serp_hash_md5_y(b: &SBytes) -> SStr { hex_lower(&md5_digest(&b.v)) }

// ---------- rtlib: serp_uuid / serp_secrets (OS CSPRNG entropy) ----------

#[cfg(windows)]
#[link(name = "bcrypt")]
extern "system" {
    fn BCryptGenRandom(alg: *mut std::ffi::c_void, buf: *mut u8, len: u32, flags: u32) -> i32;
}

#[cfg(windows)]
fn serp_entropy(buf: &mut [u8]) {
    // BCRYPT_USE_SYSTEM_PREFERRED_RNG = 0x02
    let status = unsafe {
        BCryptGenRandom(std::ptr::null_mut(), buf.as_mut_ptr(), buf.len() as u32, 2)
    };
    if status != 0 {
        serp_abort(SerpErr::new("OSError", "system entropy source failed".into()));
    }
}

#[cfg(not(windows))]
fn serp_entropy(buf: &mut [u8]) {
    use std::io::Read;
    let mut f = match std::fs::File::open("/dev/urandom") {
        Ok(f) => f,
        Err(_) => serp_abort(SerpErr::new("OSError", "system entropy source failed".into())),
    };
    if f.read_exact(buf).is_err() {
        serp_abort(SerpErr::new("OSError", "system entropy source failed".into()));
    }
}

fn serp_uuid4() -> SStr {
    let mut b = [0u8; 16];
    serp_entropy(&mut b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    let hex = hex_lower(&b);
    let h = hex.as_str();
    sstring(format!("{}-{}-{}-{}-{}", &h[0..8], &h[8..12], &h[12..16], &h[16..20], &h[20..32]))
}

fn serp_secrets_randbits(k: i64) -> SRes<i64> {
    if k <= 0 {
        return serp_err("ValueError", "number of bits must be greater than zero".into());
    }
    if k > 63 {
        return serp_err("OverflowError",
                        "randbits(k) with k > 63 exceeds the native int width".into());
    }
    let mut b = [0u8; 8];
    serp_entropy(&mut b);
    Ok((u64::from_le_bytes(b) >> (64 - k as u32)) as i64)
}

fn serp_secrets_token_bytes(n: i64) -> SRes<SBytes> {
    if n < 0 {
        return serp_err("ValueError", "negative argument not allowed".into());
    }
    let mut buf = vec![0u8; n as usize];
    serp_entropy(&mut buf);
    Ok(sbytes(buf))
}

fn serp_secrets_token_hex(n: i64) -> SRes<SStr> {
    if n < 0 {
        return serp_err("ValueError", "negative argument not allowed".into());
    }
    let mut buf = vec![0u8; n as usize];
    serp_entropy(&mut buf);
    Ok(hex_lower(&buf))
}

fn serp_secrets_token_urlsafe(n: i64) -> SRes<SStr> {
    if n < 0 {
        return serp_err("ValueError", "negative argument not allowed".into());
    }
    let mut buf = vec![0u8; n as usize];
    serp_entropy(&mut buf);
    let alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    let mut i = 0usize;
    while i < buf.len() {
        let b0 = buf[i] as u32;
        let b1 = if i + 1 < buf.len() { buf[i + 1] as u32 } else { 0 };
        let b2 = if i + 2 < buf.len() { buf[i + 2] as u32 } else { 0 };
        let v = (b0 << 16) | (b1 << 8) | b2;
        out.push(alphabet[(v >> 18) as usize & 63] as char);
        out.push(alphabet[(v >> 12) as usize & 63] as char);
        if i + 1 < buf.len() { out.push(alphabet[(v >> 6) as usize & 63] as char); }
        if i + 2 < buf.len() { out.push(alphabet[v as usize & 63] as char); }
        i += 3;
    }
    Ok(sstring(out))
}

fn serp_secrets_randbelow(n: i64) -> SRes<i64> {
    if n <= 0 {
        return serp_err("ValueError", "Upper bound must be positive.".into());
    }
    let bound = n as u64;
    let limit = u64::MAX - (u64::MAX % bound);
    loop {
        let mut b = [0u8; 8];
        serp_entropy(&mut b);
        let v = u64::from_le_bytes(b);
        if v < limit {
            return Ok((v % bound) as i64);
        }
    }
}

// ---------- rtlib: serp_zlib (self-contained DEFLATE/INFLATE; no crates) ----------

fn crc32_of(data: &[u8]) -> u32 {
    let mut crc: u32 = !0;
    for &b in data {
        crc ^= b as u32;
        for _ in 0..8 {
            let m = (crc & 1).wrapping_neg();
            crc = (crc >> 1) ^ (0xEDB88320 & m);
        }
    }
    !crc
}

fn adler32_of(data: &[u8]) -> u32 {
    let mut a: u32 = 1;
    let mut b: u32 = 0;
    for chunk in data.chunks(5552) {
        for &x in chunk {
            a += x as u32;
            b += a;
        }
        a %= 65521;
        b %= 65521;
    }
    (b << 16) | a
}

fn serp_zlib_crc32(b: &SBytes) -> i64 { crc32_of(&b.v) as i64 }
fn serp_zlib_adler32(b: &SBytes) -> i64 { adler32_of(&b.v) as i64 }

fn serp_zlib_crc32_seeded(b: &SBytes, value: i64) -> i64 {
    let mut crc: u32 = !(value as u32);
    for &byte in b.v.iter() {
        crc ^= byte as u32;
        for _ in 0..8 {
            let m = (crc & 1).wrapping_neg();
            crc = (crc >> 1) ^ (0xEDB88320 & m);
        }
    }
    (!crc) as i64
}

fn serp_zlib_adler32_seeded(b: &SBytes, value: i64) -> i64 {
    let v = value as u32;
    let mut a: u32 = v & 0xffff;
    let mut hi: u32 = (v >> 16) & 0xffff;
    for chunk in b.v.chunks(5552) {
        for &x in chunk {
            a += x as u32;
            hi += a;
        }
        a %= 65521;
        hi %= 65521;
    }
    ((hi << 16) | a) as i64
}

const ZLEN_BASE: [u16; 29] = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43,
                              51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
const ZLEN_EXTRA: [u8; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3,
                              4, 4, 4, 4, 5, 5, 5, 5, 0];
const ZDIST_BASE: [u16; 30] = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257,
                               385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289,
                               16385, 24577];
const ZDIST_EXTRA: [u8; 30] = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
                               9, 9, 10, 10, 11, 11, 12, 12, 13, 13];

struct ZBitW {
    out: Vec<u8>,
    acc: u32,
    bit: u32,
}

impl ZBitW {
    fn new() -> ZBitW { ZBitW { out: Vec::new(), acc: 0, bit: 0 } }

    fn put(&mut self, v: u32, n: u32) {
        self.acc |= v << self.bit;
        self.bit += n;
        while self.bit >= 8 {
            self.out.push((self.acc & 0xff) as u8);
            self.acc >>= 8;
            self.bit -= 8;
        }
    }

    fn put_huff(&mut self, code: u32, n: u32) {
        let mut r = 0u32;
        for i in 0..n {
            r |= ((code >> i) & 1) << (n - 1 - i);
        }
        self.put(r, n);
    }

    fn finish(mut self) -> Vec<u8> {
        if self.bit > 0 {
            self.out.push((self.acc & 0xff) as u8);
        }
        self.out
    }
}

fn zfixed_lit(bw: &mut ZBitW, sym: u32) {
    if sym <= 143 {
        bw.put_huff(0x30 + sym, 8);
    } else if sym <= 255 {
        bw.put_huff(0x190 + (sym - 144), 9);
    } else if sym <= 279 {
        bw.put_huff(sym - 256, 7);
    } else {
        bw.put_huff(0xC0 + (sym - 280), 8);
    }
}

fn zemit_match(bw: &mut ZBitW, len: usize, dist: usize) {
    let mut li = 28usize;
    while ZLEN_BASE[li] as usize > len {
        li -= 1;
    }
    zfixed_lit(bw, 257 + li as u32);
    bw.put((len - ZLEN_BASE[li] as usize) as u32, ZLEN_EXTRA[li] as u32);
    let mut di = 29usize;
    while ZDIST_BASE[di] as usize > dist {
        di -= 1;
    }
    bw.put_huff(di as u32, 5);
    bw.put((dist - ZDIST_BASE[di] as usize) as u32, ZDIST_EXTRA[di] as u32);
}

fn deflate_stored(data: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(data.len() + data.len() / 65535 * 5 + 6);
    if data.is_empty() {
        out.extend_from_slice(&[0x01, 0x00, 0x00, 0xff, 0xff]);
        return out;
    }
    let mut i = 0usize;
    while i < data.len() {
        let end = (i + 65535).min(data.len());
        let chunk = &data[i..end];
        out.push(if end == data.len() { 1 } else { 0 });
        out.extend_from_slice(&(chunk.len() as u16).to_le_bytes());
        out.extend_from_slice(&(!(chunk.len() as u16)).to_le_bytes());
        out.extend_from_slice(chunk);
        i = end;
    }
    out
}

fn zhash3(d: &[u8], i: usize) -> usize {
    (((d[i] as usize) << 10) ^ ((d[i + 1] as usize) << 5) ^ (d[i + 2] as usize)) & 0x7fff
}

fn deflate_fixed(data: &[u8], level: i64) -> Vec<u8> {
    let max_chain: usize = 8usize << level.clamp(1, 9);
    let n = data.len();
    let mut head = vec![-1i64; 1 << 15];
    let mut prev = vec![-1i64; n.max(1)];
    let mut bw = ZBitW::new();
    bw.put(1, 1);
    bw.put(1, 2);
    let mut i = 0usize;
    while i < n {
        let mut best_len = 0usize;
        let mut best_dist = 0usize;
        if i + 3 <= n {
            let h = zhash3(data, i);
            let mut cand = head[h];
            let mut chain = 0usize;
            let limit = (n - i).min(258);
            while cand >= 0 && chain < max_chain {
                let c = cand as usize;
                if i - c <= 32768 {
                    let mut l = 0usize;
                    while l < limit && data[c + l] == data[i + l] {
                        l += 1;
                    }
                    if l > best_len {
                        best_len = l;
                        best_dist = i - c;
                        if l == limit {
                            break;
                        }
                    }
                } else {
                    break;
                }
                cand = prev[c];
                chain += 1;
            }
        }
        if best_len >= 3 {
            zemit_match(&mut bw, best_len, best_dist);
            let stop = (i + best_len).min(n.saturating_sub(2));
            let mut j = i;
            while j < stop {
                let h = zhash3(data, j);
                prev[j] = head[h];
                head[h] = j as i64;
                j += 1;
            }
            i += best_len;
        } else {
            zfixed_lit(&mut bw, data[i] as u32);
            if i + 3 <= n {
                let h = zhash3(data, i);
                prev[i] = head[h];
                head[h] = i as i64;
            }
            i += 1;
        }
    }
    zfixed_lit(&mut bw, 256);
    bw.finish()
}

fn zlib_check_level(level: i64) -> SRes<()> {
    if !(0..=9).contains(&level) {
        return serp_err("ValueError", "Bad compression level".into());
    }
    Ok(())
}

fn deflate_raw(data: &[u8], level: i64) -> Vec<u8> {
    if level == 0 {
        deflate_stored(data)
    } else {
        deflate_fixed(data, level)
    }
}

fn serp_zlib_deflate(b: &SBytes, level: i64) -> SRes<SBytes> {
    zlib_check_level(level)?;
    Ok(sbytes(deflate_raw(&b.v, level)))
}

fn serp_zlib_compress(b: &SBytes, level: i64) -> SRes<SBytes> {
    zlib_check_level(level)?;
    let mut out = vec![0x78u8, 0x9c];
    out.extend_from_slice(&deflate_raw(&b.v, level));
    out.extend_from_slice(&adler32_of(&b.v).to_be_bytes());
    Ok(sbytes(out))
}

fn serp_zlib_gzip_compress(b: &SBytes, level: i64) -> SRes<SBytes> {
    zlib_check_level(level)?;
    let mut out = vec![0x1fu8, 0x8b, 8, 0, 0, 0, 0, 0, 0, 255];
    out.extend_from_slice(&deflate_raw(&b.v, level));
    out.extend_from_slice(&crc32_of(&b.v).to_le_bytes());
    out.extend_from_slice(&(b.v.len() as u32).to_le_bytes());
    Ok(sbytes(out))
}

struct ZBitR<'a> {
    d: &'a [u8],
    pos: usize,
    acc: u32,
    bit: u32,
}

impl<'a> ZBitR<'a> {
    fn new(d: &'a [u8]) -> ZBitR<'a> { ZBitR { d, pos: 0, acc: 0, bit: 0 } }

    fn bits(&mut self, n: u32) -> Result<u32, ()> {
        while self.bit < n {
            if self.pos >= self.d.len() {
                return Err(());
            }
            self.acc |= (self.d[self.pos] as u32) << self.bit;
            self.pos += 1;
            self.bit += 8;
        }
        let v = self.acc & ((1u32 << n) - 1);
        self.acc >>= n;
        self.bit -= n;
        Ok(v)
    }

    fn align(&mut self) {
        self.acc = 0;
        self.bit = 0;
    }
}

struct ZHuff {
    count: [u16; 16],
    sym: Vec<u16>,
}

fn zhuff_build(lens: &[u8]) -> Result<ZHuff, ()> {
    let mut count = [0u16; 16];
    for &l in lens {
        count[l as usize] += 1;
    }
    if count[0] as usize == lens.len() {
        return Ok(ZHuff { count, sym: Vec::new() });
    }
    let mut left: i64 = 1;
    for l in 1..16 {
        left <<= 1;
        left -= count[l] as i64;
        if left < 0 {
            return Err(());
        }
    }
    let mut offs = [0u16; 16];
    for l in 1..15 {
        offs[l + 1] = offs[l] + count[l];
    }
    let mut sym = vec![0u16; lens.len()];
    for (i, &l) in lens.iter().enumerate() {
        if l != 0 {
            sym[offs[l as usize] as usize] = i as u16;
            offs[l as usize] += 1;
        }
    }
    Ok(ZHuff { count, sym })
}

fn zhuff_decode(br: &mut ZBitR, h: &ZHuff) -> Result<u16, ()> {
    let mut code: i64 = 0;
    let mut first: i64 = 0;
    let mut index: i64 = 0;
    for len in 1..=15usize {
        code |= br.bits(1)? as i64;
        let cnt = h.count[len] as i64;
        if code - first < cnt {
            return Ok(h.sym[(index + (code - first)) as usize]);
        }
        index += cnt;
        first = (first + cnt) << 1;
        code <<= 1;
    }
    Err(())
}

fn inflate_raw(data: &[u8]) -> Result<Vec<u8>, ()> {
    let mut br = ZBitR::new(data);
    let mut out: Vec<u8> = Vec::new();
    loop {
        let bfinal = br.bits(1)?;
        let btype = br.bits(2)?;
        match btype {
            0 => {
                br.align();
                if br.pos + 4 > data.len() {
                    return Err(());
                }
                let len = u16::from_le_bytes([data[br.pos], data[br.pos + 1]]) as usize;
                let nlen = u16::from_le_bytes([data[br.pos + 2], data[br.pos + 3]]);
                if nlen != !(len as u16) {
                    return Err(());
                }
                br.pos += 4;
                if br.pos + len > data.len() {
                    return Err(());
                }
                out.extend_from_slice(&data[br.pos..br.pos + len]);
                br.pos += len;
            }
            1 | 2 => {
                let (lit, dist);
                if btype == 1 {
                    let mut ll = [0u8; 288];
                    for i in 0..144 { ll[i] = 8; }
                    for i in 144..256 { ll[i] = 9; }
                    for i in 256..280 { ll[i] = 7; }
                    for i in 280..288 { ll[i] = 8; }
                    lit = zhuff_build(&ll)?;
                    dist = zhuff_build(&[5u8; 30])?;
                } else {
                    let hlit = br.bits(5)? as usize + 257;
                    let hdist = br.bits(5)? as usize + 1;
                    let hclen = br.bits(4)? as usize + 4;
                    if hlit > 286 || hdist > 30 {
                        return Err(());
                    }
                    const ORDER: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4,
                                                12, 3, 13, 2, 14, 1, 15];
                    let mut cl = [0u8; 19];
                    for i in 0..hclen {
                        cl[ORDER[i]] = br.bits(3)? as u8;
                    }
                    let clh = zhuff_build(&cl)?;
                    let mut lens = vec![0u8; hlit + hdist];
                    let mut i = 0usize;
                    while i < hlit + hdist {
                        let sym = zhuff_decode(&mut br, &clh)?;
                        match sym {
                            0..=15 => {
                                lens[i] = sym as u8;
                                i += 1;
                            }
                            16 => {
                                if i == 0 {
                                    return Err(());
                                }
                                let p = lens[i - 1];
                                let rep = 3 + br.bits(2)? as usize;
                                if i + rep > lens.len() {
                                    return Err(());
                                }
                                for _ in 0..rep {
                                    lens[i] = p;
                                    i += 1;
                                }
                            }
                            17 => {
                                let rep = 3 + br.bits(3)? as usize;
                                if i + rep > lens.len() {
                                    return Err(());
                                }
                                i += rep;
                            }
                            18 => {
                                let rep = 11 + br.bits(7)? as usize;
                                if i + rep > lens.len() {
                                    return Err(());
                                }
                                i += rep;
                            }
                            _ => return Err(()),
                        }
                    }
                    lit = zhuff_build(&lens[..hlit])?;
                    dist = zhuff_build(&lens[hlit..])?;
                }
                loop {
                    let sym = zhuff_decode(&mut br, &lit)?;
                    if sym < 256 {
                        out.push(sym as u8);
                    } else if sym == 256 {
                        break;
                    } else {
                        let li = sym as usize - 257;
                        if li >= 29 {
                            return Err(());
                        }
                        let len = ZLEN_BASE[li] as usize
                            + br.bits(ZLEN_EXTRA[li] as u32)? as usize;
                        let ds = zhuff_decode(&mut br, &dist)? as usize;
                        if ds >= 30 {
                            return Err(());
                        }
                        let d = ZDIST_BASE[ds] as usize
                            + br.bits(ZDIST_EXTRA[ds] as u32)? as usize;
                        if d > out.len() {
                            return Err(());
                        }
                        let start = out.len() - d;
                        for k in 0..len {
                            let b = out[start + k];
                            out.push(b);
                        }
                    }
                }
            }
            _ => return Err(()),
        }
        if bfinal == 1 {
            break;
        }
    }
    Ok(out)
}

fn zlib_bad() -> SerpErr { SerpErr::new("ValueError", "invalid compressed data".into()) }

fn serp_zlib_inflate(b: &SBytes) -> SRes<SBytes> {
    match inflate_raw(&b.v) {
        Ok(v) => Ok(sbytes(v)),
        Err(()) => Err(zlib_bad()),
    }
}

fn serp_zlib_decompress(b: &SBytes) -> SRes<SBytes> {
    let d = &b.v;
    if d.len() < 6 || d[0] & 0x0f != 8 {
        return Err(zlib_bad());
    }
    if ((d[0] as u32) * 256 + d[1] as u32) % 31 != 0 || d[1] & 0x20 != 0 {
        return Err(zlib_bad());
    }
    let body = match inflate_raw(&d[2..d.len() - 4]) {
        Ok(v) => v,
        Err(()) => return Err(zlib_bad()),
    };
    let want = u32::from_be_bytes([d[d.len() - 4], d[d.len() - 3],
                                   d[d.len() - 2], d[d.len() - 1]]);
    if adler32_of(&body) != want {
        return Err(zlib_bad());
    }
    Ok(sbytes(body))
}

fn serp_zlib_gzip_decompress(b: &SBytes) -> SRes<SBytes> {
    let d = &b.v;
    if d.len() < 18 || d[0] != 0x1f || d[1] != 0x8b || d[2] != 8 {
        return Err(zlib_bad());
    }
    let flg = d[3];
    let mut i = 10usize;
    if flg & 0x04 != 0 {
        if i + 2 > d.len() {
            return Err(zlib_bad());
        }
        let xlen = u16::from_le_bytes([d[i], d[i + 1]]) as usize;
        i += 2 + xlen;
    }
    if flg & 0x08 != 0 {
        while i < d.len() && d[i] != 0 { i += 1; }
        i += 1;
    }
    if flg & 0x10 != 0 {
        while i < d.len() && d[i] != 0 { i += 1; }
        i += 1;
    }
    if flg & 0x02 != 0 {
        i += 2;
    }
    if i + 8 > d.len() {
        return Err(zlib_bad());
    }
    let body = match inflate_raw(&d[i..d.len() - 8]) {
        Ok(v) => v,
        Err(()) => return Err(zlib_bad()),
    };
    let want_crc = u32::from_le_bytes([d[d.len() - 8], d[d.len() - 7],
                                       d[d.len() - 6], d[d.len() - 5]]);
    let want_len = u32::from_le_bytes([d[d.len() - 4], d[d.len() - 3],
                                       d[d.len() - 2], d[d.len() - 1]]);
    if crc32_of(&body) != want_crc || body.len() as u32 != want_len {
        return Err(zlib_bad());
    }
    Ok(sbytes(body))
}

// ---------- rtlib: serp_sqlite (system SQLite loaded dynamically; no crates,
// no link-time dependency — winsqlite3.dll on Windows, libsqlite3 elsewhere) ----------

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn LoadLibraryA(name: *const u8) -> *mut std::ffi::c_void;
    fn GetProcAddress(h: *mut std::ffi::c_void, name: *const u8) -> *mut std::ffi::c_void;
}

#[cfg(windows)]
fn sql_lib_open() -> *mut std::ffi::c_void {
    unsafe {
        let h = LoadLibraryA(b"winsqlite3.dll\0".as_ptr());
        if !h.is_null() { return h; }
        LoadLibraryA(b"sqlite3.dll\0".as_ptr())
    }
}

#[cfg(windows)]
fn sql_lib_sym(h: *mut std::ffi::c_void, name: &[u8]) -> *mut std::ffi::c_void {
    unsafe { GetProcAddress(h, name.as_ptr()) }
}

#[cfg(all(unix, not(target_os = "macos")))]
#[link(name = "dl")]
extern "C" {
    fn dlopen(name: *const u8, flag: i32) -> *mut std::ffi::c_void;
    fn dlsym(h: *mut std::ffi::c_void, name: *const u8) -> *mut std::ffi::c_void;
}

#[cfg(target_os = "macos")]
extern "C" {
    fn dlopen(name: *const u8, flag: i32) -> *mut std::ffi::c_void;
    fn dlsym(h: *mut std::ffi::c_void, name: *const u8) -> *mut std::ffi::c_void;
}

#[cfg(all(unix, not(target_os = "macos")))]
fn sql_lib_open() -> *mut std::ffi::c_void {
    unsafe {
        let h = dlopen(b"libsqlite3.so.0\0".as_ptr(), 2);
        if !h.is_null() { return h; }
        dlopen(b"libsqlite3.so\0".as_ptr(), 2)
    }
}

#[cfg(target_os = "macos")]
fn sql_lib_open() -> *mut std::ffi::c_void {
    unsafe { dlopen(b"libsqlite3.dylib\0".as_ptr(), 2) }
}

#[cfg(unix)]
fn sql_lib_sym(h: *mut std::ffi::c_void, name: &[u8]) -> *mut std::ffi::c_void {
    unsafe { dlsym(h, name.as_ptr()) }
}

type CVoidP = *mut std::ffi::c_void;

struct SqliteApi {
    open_v2: unsafe extern "C" fn(*const u8, *mut CVoidP, i32, *const u8) -> i32,
    close_v2: unsafe extern "C" fn(CVoidP) -> i32,
    prepare_v2: unsafe extern "C" fn(CVoidP, *const u8, i32, *mut CVoidP, *mut *const u8) -> i32,
    step: unsafe extern "C" fn(CVoidP) -> i32,
    finalize: unsafe extern "C" fn(CVoidP) -> i32,
    reset: unsafe extern "C" fn(CVoidP) -> i32,
    errmsg: unsafe extern "C" fn(CVoidP) -> *const u8,
    changes: unsafe extern "C" fn(CVoidP) -> i32,
    last_rowid: unsafe extern "C" fn(CVoidP) -> i64,
    bind_int64: unsafe extern "C" fn(CVoidP, i32, i64) -> i32,
    bind_double: unsafe extern "C" fn(CVoidP, i32, f64) -> i32,
    bind_text: unsafe extern "C" fn(CVoidP, i32, *const u8, i32, isize) -> i32,
    bind_blob: unsafe extern "C" fn(CVoidP, i32, *const u8, i32, isize) -> i32,
    bind_null: unsafe extern "C" fn(CVoidP, i32) -> i32,
    column_count: unsafe extern "C" fn(CVoidP) -> i32,
    column_type: unsafe extern "C" fn(CVoidP, i32) -> i32,
    column_int64: unsafe extern "C" fn(CVoidP, i32) -> i64,
    column_double: unsafe extern "C" fn(CVoidP, i32) -> f64,
    column_text: unsafe extern "C" fn(CVoidP, i32) -> *const u8,
    column_bytes: unsafe extern "C" fn(CVoidP, i32) -> i32,
    column_blob: unsafe extern "C" fn(CVoidP, i32) -> *const u8,
}

static mut SQLITE_API: Option<SqliteApi> = None;

struct SqlStmtRec {
    p: CVoidP,
    db: CVoidP,
}

static mut SQL_DBS: Vec<Option<CVoidP>> = Vec::new();
static mut SQL_STMTS: Vec<Option<SqlStmtRec>> = Vec::new();

fn sqlite_api() -> SRes<&'static SqliteApi> {
    unsafe {
        let slot = &mut *std::ptr::addr_of_mut!(SQLITE_API);
        if slot.is_none() {
            let h = sql_lib_open();
            if h.is_null() {
                return serp_err("OSError", "SQLite library not found".into());
            }
            macro_rules! sym {
                ($name:literal) => {{
                    let p = sql_lib_sym(h, $name);
                    if p.is_null() {
                        return serp_err("OSError", "SQLite library not found".into());
                    }
                    std::mem::transmute(p)
                }};
            }
            *slot = Some(SqliteApi {
                open_v2: sym!(b"sqlite3_open_v2\0"),
                close_v2: sym!(b"sqlite3_close_v2\0"),
                prepare_v2: sym!(b"sqlite3_prepare_v2\0"),
                step: sym!(b"sqlite3_step\0"),
                finalize: sym!(b"sqlite3_finalize\0"),
                reset: sym!(b"sqlite3_reset\0"),
                errmsg: sym!(b"sqlite3_errmsg\0"),
                changes: sym!(b"sqlite3_changes\0"),
                last_rowid: sym!(b"sqlite3_last_insert_rowid\0"),
                bind_int64: sym!(b"sqlite3_bind_int64\0"),
                bind_double: sym!(b"sqlite3_bind_double\0"),
                bind_text: sym!(b"sqlite3_bind_text\0"),
                bind_blob: sym!(b"sqlite3_bind_blob\0"),
                bind_null: sym!(b"sqlite3_bind_null\0"),
                column_count: sym!(b"sqlite3_column_count\0"),
                column_type: sym!(b"sqlite3_column_type\0"),
                column_int64: sym!(b"sqlite3_column_int64\0"),
                column_double: sym!(b"sqlite3_column_double\0"),
                column_text: sym!(b"sqlite3_column_text\0"),
                column_bytes: sym!(b"sqlite3_column_bytes\0"),
                column_blob: sym!(b"sqlite3_column_blob\0"),
            });
        }
        Ok(slot.as_ref().unwrap())
    }
}

unsafe fn sql_cstr(p: *const u8) -> String {
    if p.is_null() {
        return String::new();
    }
    let mut n = 0usize;
    while *p.add(n) != 0 {
        n += 1;
    }
    String::from_utf8_lossy(std::slice::from_raw_parts(p, n)).into_owned()
}

fn sql_db_err(db: CVoidP) -> SerpErr {
    let api = match sqlite_api() { Ok(a) => a, Err(e) => return e };
    SerpErr::new("ValueError", unsafe { sql_cstr((api.errmsg)(db)) })
}

fn sql_db(h: i64) -> SRes<CVoidP> {
    unsafe {
        let dbs = &*std::ptr::addr_of!(SQL_DBS);
        if h >= 1 && (h as usize) <= dbs.len() {
            if let Some(p) = dbs[h as usize - 1] {
                return Ok(p);
            }
        }
        serp_err("ValueError", "invalid database handle".into())
    }
}

fn sql_stmt(h: i64) -> SRes<(CVoidP, CVoidP)> {
    unsafe {
        let ss = &*std::ptr::addr_of!(SQL_STMTS);
        if h >= 1 && (h as usize) <= ss.len() {
            if let Some(rec) = &ss[h as usize - 1] {
                return Ok((rec.p, rec.db));
            }
        }
        serp_err("ValueError", "invalid statement handle".into())
    }
}

fn sql_prepare_raw(db: CVoidP, sql: &str) -> SRes<CVoidP> {
    let api = sqlite_api()?;
    let mut buf = sql.as_bytes().to_vec();
    buf.push(0);
    let mut stmt: CVoidP = std::ptr::null_mut();
    let mut tail: *const u8 = std::ptr::null();
    let rc = unsafe { (api.prepare_v2)(db, buf.as_ptr(), -1, &mut stmt, &mut tail) };
    if rc != 0 {
        return Err(sql_db_err(db));
    }
    if stmt.is_null() {
        return serp_err("ValueError", "empty SQL statement".into());
    }
    Ok(stmt)
}

fn serp_sqlite_open(path: &str) -> SRes<i64> {
    let api = sqlite_api()?;
    let mut buf = path.as_bytes().to_vec();
    buf.push(0);
    let mut db: CVoidP = std::ptr::null_mut();
    // SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE = 6
    let rc = unsafe { (api.open_v2)(buf.as_ptr(), &mut db, 6, std::ptr::null()) };
    if rc != 0 {
        let msg = if db.is_null() {
            "unable to open database file".to_string()
        } else {
            let m = unsafe { sql_cstr((api.errmsg)(db)) };
            unsafe { (api.close_v2)(db) };
            m
        };
        return serp_err("ValueError", msg);
    }
    unsafe {
        let dbs = &mut *std::ptr::addr_of_mut!(SQL_DBS);
        dbs.push(Some(db));
        Ok(dbs.len() as i64)
    }
}

fn serp_sqlite_close(h: i64) -> SRes<()> {
    let db = sql_db(h)?;
    let api = sqlite_api()?;
    unsafe {
        (api.close_v2)(db);
        let dbs = &mut *std::ptr::addr_of_mut!(SQL_DBS);
        dbs[h as usize - 1] = None;
    }
    Ok(())
}

fn serp_sqlite_execute(h: i64, sql: &str) -> SRes<()> {
    let db = sql_db(h)?;
    let api = sqlite_api()?;
    let stmt = sql_prepare_raw(db, sql)?;
    loop {
        let rc = unsafe { (api.step)(stmt) };
        if rc == 101 {
            break;
        }
        if rc != 100 {
            let e = sql_db_err(db);
            unsafe { (api.finalize)(stmt) };
            return Err(e);
        }
    }
    unsafe { (api.finalize)(stmt) };
    Ok(())
}

fn serp_sqlite_changes(h: i64) -> SRes<i64> {
    let db = sql_db(h)?;
    let api = sqlite_api()?;
    Ok(unsafe { (api.changes)(db) } as i64)
}

fn serp_sqlite_last_rowid(h: i64) -> SRes<i64> {
    let db = sql_db(h)?;
    let api = sqlite_api()?;
    Ok(unsafe { (api.last_rowid)(db) })
}

fn serp_sqlite_prepare(h: i64, sql: &str) -> SRes<i64> {
    let db = sql_db(h)?;
    let stmt = sql_prepare_raw(db, sql)?;
    unsafe {
        let ss = &mut *std::ptr::addr_of_mut!(SQL_STMTS);
        ss.push(Some(SqlStmtRec { p: stmt, db }));
        Ok(ss.len() as i64)
    }
}

fn sql_bind_check(db: CVoidP, rc: i32) -> SRes<()> {
    if rc != 0 {
        return Err(sql_db_err(db));
    }
    Ok(())
}

fn serp_sqlite_bind_int(h: i64, idx: i64, v: i64) -> SRes<()> {
    let (p, db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    sql_bind_check(db, unsafe { (api.bind_int64)(p, idx as i32, v) })
}

fn serp_sqlite_bind_float(h: i64, idx: i64, v: f64) -> SRes<()> {
    let (p, db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    sql_bind_check(db, unsafe { (api.bind_double)(p, idx as i32, v) })
}

fn serp_sqlite_bind_text(h: i64, idx: i64, v: &str) -> SRes<()> {
    let (p, db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    // SQLITE_TRANSIENT = -1: SQLite copies the buffer before returning.
    sql_bind_check(db, unsafe {
        (api.bind_text)(p, idx as i32, v.as_ptr(), v.len() as i32, -1isize)
    })
}

fn serp_sqlite_bind_blob(h: i64, idx: i64, v: &SBytes) -> SRes<()> {
    let (p, db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    sql_bind_check(db, unsafe {
        (api.bind_blob)(p, idx as i32, v.v.as_ptr(), v.v.len() as i32, -1isize)
    })
}

fn serp_sqlite_bind_null(h: i64, idx: i64) -> SRes<()> {
    let (p, db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    sql_bind_check(db, unsafe { (api.bind_null)(p, idx as i32) })
}

fn serp_sqlite_step(h: i64) -> SRes<bool> {
    let (p, db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    let rc = unsafe { (api.step)(p) };
    if rc == 100 {
        return Ok(true);
    }
    if rc == 101 {
        return Ok(false);
    }
    Err(sql_db_err(db))
}

fn serp_sqlite_column_count(h: i64) -> SRes<i64> {
    let (p, _db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    Ok(unsafe { (api.column_count)(p) } as i64)
}

fn serp_sqlite_col_type(h: i64, i: i64) -> SRes<i64> {
    let (p, _db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    Ok(unsafe { (api.column_type)(p, i as i32) } as i64)
}

fn serp_sqlite_col_int(h: i64, i: i64) -> SRes<i64> {
    let (p, _db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    Ok(unsafe { (api.column_int64)(p, i as i32) })
}

fn serp_sqlite_col_float(h: i64, i: i64) -> SRes<f64> {
    let (p, _db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    Ok(unsafe { (api.column_double)(p, i as i32) })
}

fn serp_sqlite_col_text(h: i64, i: i64) -> SRes<SStr> {
    let (p, _db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    unsafe {
        let t = (api.column_text)(p, i as i32);
        if t.is_null() {
            return Ok(sstr(""));
        }
        let n = (api.column_bytes)(p, i as i32) as usize;
        Ok(sstring(String::from_utf8_lossy(std::slice::from_raw_parts(t, n)).into_owned()))
    }
}

fn serp_sqlite_col_blob(h: i64, i: i64) -> SRes<SBytes> {
    let (p, _db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    unsafe {
        let b = (api.column_blob)(p, i as i32);
        let n = (api.column_bytes)(p, i as i32) as usize;
        if b.is_null() || n == 0 {
            return Ok(sbytes(Vec::new()));
        }
        Ok(sbytes(std::slice::from_raw_parts(b, n).to_vec()))
    }
}

fn serp_sqlite_reset(h: i64) -> SRes<()> {
    let (p, _db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    unsafe { (api.reset)(p) };
    Ok(())
}

fn serp_sqlite_finalize(h: i64) -> SRes<()> {
    let (p, _db) = sql_stmt(h)?;
    let api = sqlite_api()?;
    unsafe {
        (api.finalize)(p);
        let ss = &mut *std::ptr::addr_of_mut!(SQL_STMTS);
        ss[h as usize - 1] = None;
    }
    Ok(())
}

// ---------- rtlib: serp_socket (std::net TCP/UDP; error messages normalized
// identically in the CPython delegate so dual runs stay byte-identical) ----------

enum SockKind {
    Tcp(std::net::TcpStream),
    Listener(std::net::TcpListener),
    Udp(std::net::UdpSocket),
    Tls(TlsConn),
}

struct SockRec {
    kind: SockKind,
    peer: Option<(String, i64)>,
}

static mut SOCKS: Vec<Option<SockRec>> = Vec::new();

fn sock_io_err(e: &std::io::Error) -> SerpErr {
    use std::io::ErrorKind as K;
    let msg = match e.kind() {
        K::ConnectionRefused => "connection refused",
        K::TimedOut | K::WouldBlock => "timed out",
        K::ConnectionReset | K::ConnectionAborted | K::BrokenPipe => "connection reset",
        K::AddrInUse => "address in use",
        K::NotConnected => "not connected",
        _ => "socket error",
    };
    SerpErr::new("OSError", msg.to_string())
}

fn sock_push(rec: SockRec) -> i64 {
    unsafe {
        let socks = &mut *std::ptr::addr_of_mut!(SOCKS);
        socks.push(Some(rec));
        socks.len() as i64
    }
}

fn sock_get(h: i64) -> SRes<&'static mut SockRec> {
    unsafe {
        let socks = &mut *std::ptr::addr_of_mut!(SOCKS);
        if h >= 1 && (h as usize) <= socks.len() {
            if let Some(rec) = &mut socks[h as usize - 1] {
                return Ok(rec);
            }
        }
        serp_err("ValueError", "invalid socket handle".into())
    }
}

fn sock_port_ok(port: i64) -> SRes<u16> {
    if !(0..=65535).contains(&port) {
        return serp_err("ValueError", "port out of range".into());
    }
    Ok(port as u16)
}

fn sock_resolve(host: &str, port: i64) -> SRes<std::net::SocketAddr> {
    use std::net::ToSocketAddrs;
    let p = sock_port_ok(port)?;
    match (host, p).to_socket_addrs() {
        Ok(mut it) => match it.next() {
            Some(a) => Ok(a),
            None => serp_err("OSError", "address resolution failed".into()),
        },
        Err(_) => serp_err("OSError", "address resolution failed".into()),
    }
}

fn serp_sock_connect(host: &str, port: i64, timeout_ms: i64) -> SRes<i64> {
    let addr = sock_resolve(host, port)?;
    let stream = if timeout_ms > 0 {
        std::net::TcpStream::connect_timeout(
            &addr, std::time::Duration::from_millis(timeout_ms as u64))
    } else {
        std::net::TcpStream::connect(addr)
    };
    match stream {
        Ok(s) => Ok(sock_push(SockRec { kind: SockKind::Tcp(s), peer: None })),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_listen(host: &str, port: i64) -> SRes<i64> {
    let addr = sock_resolve(host, port)?;
    match std::net::TcpListener::bind(addr) {
        Ok(l) => Ok(sock_push(SockRec { kind: SockKind::Listener(l), peer: None })),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_accept(h: i64) -> SRes<i64> {
    let rec = sock_get(h)?;
    match &rec.kind {
        SockKind::Listener(l) => match l.accept() {
            Ok((s, _)) => Ok(sock_push(SockRec { kind: SockKind::Tcp(s), peer: None })),
            Err(e) => Err(sock_io_err(&e)),
        },
        _ => serp_err("ValueError", "accept() needs a listener".into()),
    }
}

fn serp_sock_send(h: i64, data: &SBytes) -> SRes<i64> {
    use std::io::Write;
    let rec = sock_get(h)?;
    match &mut rec.kind {
        SockKind::Tcp(s) => match s.write_all(&data.v) {
            Ok(()) => Ok(data.v.len() as i64),
            Err(e) => Err(sock_io_err(&e)),
        },
        SockKind::Tls(c) => {
            tls_write_conn(c, &data.v)?;
            Ok(data.v.len() as i64)
        }
        _ => serp_err("ValueError", "send() needs a TCP stream".into()),
    }
}

fn serp_sock_recv(h: i64, maxlen: i64) -> SRes<SBytes> {
    use std::io::Read;
    if maxlen <= 0 {
        return serp_err("ValueError", "maxlen must be positive".into());
    }
    let rec = sock_get(h)?;
    match &mut rec.kind {
        SockKind::Tcp(s) => {
            let mut buf = vec![0u8; maxlen as usize];
            match s.read(&mut buf) {
                Ok(n) => { buf.truncate(n); Ok(sbytes(buf)) }
                Err(e) => Err(sock_io_err(&e)),
            }
        }
        SockKind::Tls(c) => Ok(sbytes(tls_read_conn(c, maxlen as usize)?)),
        _ => serp_err("ValueError", "recv() needs a TCP stream".into()),
    }
}

fn serp_sock_shutdown_write(h: i64) -> SRes<()> {
    let rec = sock_get(h)?;
    match &rec.kind {
        SockKind::Tcp(s) => match s.shutdown(std::net::Shutdown::Write) {
            Ok(()) => Ok(()),
            Err(e) => Err(sock_io_err(&e)),
        },
        SockKind::Tls(c) => match c.tcp.shutdown(std::net::Shutdown::Write) {
            Ok(()) => Ok(()),
            Err(e) => Err(sock_io_err(&e)),
        },
        _ => serp_err("ValueError", "shutdown_write() needs a TCP stream".into()),
    }
}

fn serp_sock_set_timeout(h: i64, ms: i64) -> SRes<()> {
    let rec = sock_get(h)?;
    let dur = if ms > 0 {
        Some(std::time::Duration::from_millis(ms as u64))
    } else {
        None
    };
    let r = match &rec.kind {
        SockKind::Tcp(s) => s.set_read_timeout(dur).and_then(|_| s.set_write_timeout(dur)),
        SockKind::Tls(c) => c.tcp.set_read_timeout(dur).and_then(|_| c.tcp.set_write_timeout(dur)),
        SockKind::Udp(u) => u.set_read_timeout(dur).and_then(|_| u.set_write_timeout(dur)),
        SockKind::Listener(_) =>
            return serp_err("ValueError", "cannot set timeout on a listener".into()),
    };
    match r {
        Ok(()) => Ok(()),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_local_port(h: i64) -> SRes<i64> {
    let rec = sock_get(h)?;
    let addr = match &rec.kind {
        SockKind::Tcp(s) => s.local_addr(),
        SockKind::Tls(c) => c.tcp.local_addr(),
        SockKind::Listener(l) => l.local_addr(),
        SockKind::Udp(u) => u.local_addr(),
    };
    match addr {
        Ok(a) => Ok(a.port() as i64),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_close(h: i64) -> SRes<()> {
    sock_get(h)?;
    unsafe {
        let socks = &mut *std::ptr::addr_of_mut!(SOCKS);
        socks[h as usize - 1] = None;
    }
    Ok(())
}

fn serp_sock_udp_bind(host: &str, port: i64) -> SRes<i64> {
    let addr = sock_resolve(host, port)?;
    match std::net::UdpSocket::bind(addr) {
        Ok(u) => Ok(sock_push(SockRec { kind: SockKind::Udp(u), peer: None })),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_udp_send_to(h: i64, data: &SBytes, host: &str, port: i64) -> SRes<i64> {
    let addr = sock_resolve(host, port)?;
    let rec = sock_get(h)?;
    match &rec.kind {
        SockKind::Udp(u) => match u.send_to(&data.v, addr) {
            Ok(n) => Ok(n as i64),
            Err(e) => Err(sock_io_err(&e)),
        },
        _ => serp_err("ValueError", "udp_send_to() needs a UDP socket".into()),
    }
}

fn serp_sock_udp_recv_from(h: i64, maxlen: i64) -> SRes<SBytes> {
    if maxlen <= 0 {
        return serp_err("ValueError", "maxlen must be positive".into());
    }
    let rec = sock_get(h)?;
    match &rec.kind {
        SockKind::Udp(u) => {
            let mut buf = vec![0u8; maxlen as usize];
            match u.recv_from(&mut buf) {
                Ok((n, from)) => {
                    buf.truncate(n);
                    rec.peer = Some((from.ip().to_string(), from.port() as i64));
                    Ok(sbytes(buf))
                }
                Err(e) => Err(sock_io_err(&e)),
            }
        }
        _ => serp_err("ValueError", "udp_recv_from() needs a UDP socket".into()),
    }
}

fn serp_sock_udp_peer_host(h: i64) -> SRes<SStr> {
    let rec = sock_get(h)?;
    match &rec.peer {
        Some((host, _)) => Ok(sstring(host.clone())),
        None => serp_err("ValueError", "no datagram received yet".into()),
    }
}

fn serp_sock_udp_peer_port(h: i64) -> SRes<i64> {
    let rec = sock_get(h)?;
    match &rec.peer {
        Some((_, port)) => Ok(*port),
        None => serp_err("ValueError", "no datagram received yet".into()),
    }
}

// ---------- rtlib: serp_socket TLS (schannel on Windows, dlopen'd OpenSSL on
// unix; error messages normalized identically in the CPython delegate:
// OSError("certificate verify failed" / "tls handshake failed" / socket set) ----------

#[cfg(windows)]
#[repr(C)]
#[derive(Clone, Copy)]
struct TlsSecHandle {
    lo: usize,
    hi: usize,
}

#[cfg(windows)]
#[repr(C)]
struct TlsSecBuffer {
    cb: u32,
    ty: u32,
    pv: *mut std::ffi::c_void,
}

#[cfg(windows)]
#[repr(C)]
struct TlsSecBufferDesc {
    ver: u32,
    n: u32,
    bufs: *mut TlsSecBuffer,
}

#[cfg(windows)]
#[repr(C)]
struct TlsSchannelCred {
    version: u32,
    ccreds: u32,
    pacred: *mut std::ffi::c_void,
    root_store: *mut std::ffi::c_void,
    cmappers: u32,
    apmappers: *mut std::ffi::c_void,
    csupported_algs: u32,
    palg_supported_algs: *mut std::ffi::c_void,
    grbit_enabled_protocols: u32,
    min_cipher_strength: u32,
    max_cipher_strength: u32,
    session_lifespan: u32,
    flags: u32,
    cred_format: u32,
}

#[cfg(windows)]
#[repr(C)]
struct TlsStreamSizes {
    header: u32,
    trailer: u32,
    max_message: u32,
    buffers: u32,
    block_size: u32,
}

#[cfg(windows)]
#[link(name = "secur32")]
extern "system" {
    fn AcquireCredentialsHandleW(
        principal: *const u16, package: *const u16, cred_use: u32,
        logon_id: *mut std::ffi::c_void, auth_data: *const std::ffi::c_void,
        get_key_fn: *mut std::ffi::c_void, get_key_arg: *mut std::ffi::c_void,
        cred: *mut TlsSecHandle, expiry: *mut i64) -> i32;
    fn InitializeSecurityContextW(
        cred: *const TlsSecHandle, ctx: *const TlsSecHandle, target: *const u16,
        req: u32, reserved1: u32, data_rep: u32, input: *const TlsSecBufferDesc,
        reserved2: u32, new_ctx: *mut TlsSecHandle, output: *mut TlsSecBufferDesc,
        attr: *mut u32, expiry: *mut i64) -> i32;
    fn QueryContextAttributesW(ctx: *const TlsSecHandle, attr: u32,
                               buffer: *mut std::ffi::c_void) -> i32;
    fn EncryptMessage(ctx: *const TlsSecHandle, qop: u32,
                      msg: *mut TlsSecBufferDesc, seq: u32) -> i32;
    fn DecryptMessage(ctx: *const TlsSecHandle, msg: *mut TlsSecBufferDesc,
                      seq: u32, qop: *mut u32) -> i32;
    fn FreeContextBuffer(buf: *mut std::ffi::c_void) -> i32;
    fn DeleteSecurityContext(ctx: *const TlsSecHandle) -> i32;
    fn FreeCredentialsHandle(cred: *const TlsSecHandle) -> i32;
}

#[cfg(windows)]
const TLS_SEC_OK: i32 = 0;
#[cfg(windows)]
const TLS_CONTINUE_NEEDED: i32 = 0x0009_0312;
#[cfg(windows)]
const TLS_INCOMPLETE_MESSAGE: i32 = 0x8009_0318u32 as i32;
#[cfg(windows)]
const TLS_CONTEXT_EXPIRED: i32 = 0x0009_0317;

#[cfg(windows)]
struct TlsConn {
    tcp: std::net::TcpStream,
    cred: TlsSecHandle,
    ctx: TlsSecHandle,
    sizes: TlsStreamSizes,
    enc: Vec<u8>,
    dec: Vec<u8>,
    eof: bool,
}

#[cfg(windows)]
impl Drop for TlsConn {
    fn drop(&mut self) {
        unsafe {
            DeleteSecurityContext(&self.ctx);
            FreeCredentialsHandle(&self.cred);
        }
    }
}

#[cfg(windows)]
fn tls_utf16(s: &str) -> Vec<u16> {
    let mut v: Vec<u16> = s.encode_utf16().collect();
    v.push(0);
    v
}

#[cfg(windows)]
fn tls_cert_error(code: i32) -> bool {
    let c = code as u32;
    c == 0x8009_0325 || c == 0x8009_0322 || c == 0x8009_0327 || c == 0x8009_0328
        || c == 0x800B_0101 || c == 0x800B_0109 || c == 0x800B_010F || c == 0x800B_0110
}

#[cfg(windows)]
unsafe fn tls_hs_fail(cred: &TlsSecHandle, ctx: &TlsSecHandle, ctx_ok: bool, status: i32)
                      -> SRes<(TlsSecHandle, TlsSecHandle, TlsStreamSizes, Vec<u8>)> {
    if ctx_ok {
        DeleteSecurityContext(ctx);
    }
    FreeCredentialsHandle(cred);
    if tls_cert_error(status) {
        serp_err("OSError", "certificate verify failed".into())
    } else {
        serp_err("OSError", "tls handshake failed".into())
    }
}

#[cfg(windows)]
fn tls_client_handshake(tcp: &mut std::net::TcpStream, host: &str, insecure: bool)
                        -> SRes<(TlsSecHandle, TlsSecHandle, TlsStreamSizes, Vec<u8>)> {
    use std::io::{Read, Write};
    unsafe {
        let package = tls_utf16("Microsoft Unified Security Protocol Provider");
        let mut scred: TlsSchannelCred = std::mem::zeroed();
        scred.version = 4;
        scred.flags = 0x10 | 0x0040_0000 | if insecure { 0x8 } else { 0x20 };
        let mut cred = TlsSecHandle { lo: 0, hi: 0 };
        let mut expiry: i64 = 0;
        if AcquireCredentialsHandleW(std::ptr::null(), package.as_ptr(), 2,
                                     std::ptr::null_mut(),
                                     &scred as *const TlsSchannelCred as *const std::ffi::c_void,
                                     std::ptr::null_mut(), std::ptr::null_mut(),
                                     &mut cred, &mut expiry) != 0 {
            return serp_err("OSError", "tls handshake failed".into());
        }
        let target = tls_utf16(host);
        let req: u32 = 0x8 | 0x4 | 0x10 | 0x100 | 0x8000
            | if insecure { 0x0008_0000 } else { 0 };
        let mut ctx = TlsSecHandle { lo: 0, hi: 0 };
        let mut ctx_ok = false;
        let mut attr: u32 = 0;
        let mut inbuf: Vec<u8> = Vec::new();
        loop {
            let mut out0 = TlsSecBuffer { cb: 0, ty: 2, pv: std::ptr::null_mut() };
            let mut outdesc = TlsSecBufferDesc { ver: 0, n: 1, bufs: &mut out0 };
            let mut inarr = [
                TlsSecBuffer {
                    cb: inbuf.len() as u32,
                    ty: 2,
                    pv: if inbuf.is_empty() { std::ptr::null_mut() }
                        else { inbuf.as_mut_ptr() as *mut std::ffi::c_void },
                },
                TlsSecBuffer { cb: 0, ty: 0, pv: std::ptr::null_mut() },
            ];
            let indesc = TlsSecBufferDesc { ver: 0, n: 2, bufs: inarr.as_mut_ptr() };
            let status = InitializeSecurityContextW(
                &cred,
                if ctx_ok { &ctx } else { std::ptr::null() },
                target.as_ptr(), req, 0, 0,
                if ctx_ok { &indesc } else { std::ptr::null() },
                0, &mut ctx, &mut outdesc, &mut attr, &mut expiry);
            if status != TLS_INCOMPLETE_MESSAGE {
                ctx_ok = true;
                if !out0.pv.is_null() && out0.cb > 0 {
                    let tok = std::slice::from_raw_parts(out0.pv as *const u8,
                                                         out0.cb as usize).to_vec();
                    FreeContextBuffer(out0.pv);
                    if let Err(e) = tcp.write_all(&tok) {
                        DeleteSecurityContext(&ctx);
                        FreeCredentialsHandle(&cred);
                        return Err(sock_io_err(&e));
                    }
                } else if !out0.pv.is_null() {
                    FreeContextBuffer(out0.pv);
                }
                if status == TLS_SEC_OK {
                    let mut leftover: Vec<u8> = Vec::new();
                    if inarr[1].ty == 5 && inarr[1].cb > 0 {
                        let keep = inarr[1].cb as usize;
                        leftover = inbuf[inbuf.len() - keep..].to_vec();
                    }
                    let mut sizes: TlsStreamSizes = std::mem::zeroed();
                    if QueryContextAttributesW(
                        &ctx, 4, &mut sizes as *mut TlsStreamSizes as *mut std::ffi::c_void) != 0 {
                        return tls_hs_fail(&cred, &ctx, true, 1);
                    }
                    return Ok((cred, ctx, sizes, leftover));
                }
                if status != TLS_CONTINUE_NEEDED {
                    return tls_hs_fail(&cred, &ctx, true, status);
                }
                if inarr[1].ty == 5 && inarr[1].cb > 0 {
                    let keep = inarr[1].cb as usize;
                    let tail = inbuf[inbuf.len() - keep..].to_vec();
                    inbuf = tail;
                    continue;
                }
                inbuf.clear();
            }
            let mut tmp = vec![0u8; 16384];
            match tcp.read(&mut tmp) {
                Ok(0) => return tls_hs_fail(&cred, &ctx, ctx_ok, 1),
                Ok(n) => inbuf.extend_from_slice(&tmp[..n]),
                Err(e) => {
                    if ctx_ok {
                        DeleteSecurityContext(&ctx);
                    }
                    FreeCredentialsHandle(&cred);
                    return Err(sock_io_err(&e));
                }
            }
        }
    }
}

#[cfg(windows)]
fn tls_read_conn(c: &mut TlsConn, maxlen: usize) -> SRes<Vec<u8>> {
    use std::io::Read;
    unsafe {
        loop {
            if !c.dec.is_empty() {
                let n = maxlen.min(c.dec.len());
                let out: Vec<u8> = c.dec.drain(..n).collect();
                return Ok(out);
            }
            if c.eof {
                return Ok(Vec::new());
            }
            if !c.enc.is_empty() {
                let mut bufs = [
                    TlsSecBuffer {
                        cb: c.enc.len() as u32,
                        ty: 1,
                        pv: c.enc.as_mut_ptr() as *mut std::ffi::c_void,
                    },
                    TlsSecBuffer { cb: 0, ty: 0, pv: std::ptr::null_mut() },
                    TlsSecBuffer { cb: 0, ty: 0, pv: std::ptr::null_mut() },
                    TlsSecBuffer { cb: 0, ty: 0, pv: std::ptr::null_mut() },
                ];
                let mut desc = TlsSecBufferDesc { ver: 0, n: 4, bufs: bufs.as_mut_ptr() };
                let status = DecryptMessage(&c.ctx, &mut desc, 0, std::ptr::null_mut());
                if status == TLS_SEC_OK || status == TLS_CONTEXT_EXPIRED {
                    let mut extra: Vec<u8> = Vec::new();
                    for b in bufs.iter() {
                        if b.ty == 1 && b.cb > 0 && !b.pv.is_null() {
                            c.dec.extend_from_slice(std::slice::from_raw_parts(
                                b.pv as *const u8, b.cb as usize));
                        } else if b.ty == 5 && b.cb > 0 && !b.pv.is_null() {
                            extra = std::slice::from_raw_parts(
                                b.pv as *const u8, b.cb as usize).to_vec();
                        }
                    }
                    c.enc = extra;
                    if status == TLS_CONTEXT_EXPIRED {
                        c.eof = true;
                    }
                    continue;
                }
                if status != TLS_INCOMPLETE_MESSAGE {
                    return serp_err("OSError", "socket error".into());
                }
            }
            let mut tmp = vec![0u8; 16384];
            match c.tcp.read(&mut tmp) {
                Ok(0) => c.eof = true,
                Ok(n) => c.enc.extend_from_slice(&tmp[..n]),
                Err(e) => return Err(sock_io_err(&e)),
            }
        }
    }
}

#[cfg(windows)]
fn tls_write_conn(c: &mut TlsConn, data: &[u8]) -> SRes<()> {
    use std::io::Write;
    unsafe {
        let maxm = (c.sizes.max_message as usize).max(1);
        let h = c.sizes.header as usize;
        let t = c.sizes.trailer as usize;
        let mut off = 0usize;
        while off < data.len() {
            let n = (data.len() - off).min(maxm);
            let mut buf = vec![0u8; h + n + t];
            buf[h..h + n].copy_from_slice(&data[off..off + n]);
            let mut bufs = [
                TlsSecBuffer { cb: h as u32, ty: 7,
                               pv: buf.as_mut_ptr() as *mut std::ffi::c_void },
                TlsSecBuffer { cb: n as u32, ty: 1,
                               pv: buf.as_mut_ptr().add(h) as *mut std::ffi::c_void },
                TlsSecBuffer { cb: t as u32, ty: 6,
                               pv: buf.as_mut_ptr().add(h + n) as *mut std::ffi::c_void },
                TlsSecBuffer { cb: 0, ty: 0, pv: std::ptr::null_mut() },
            ];
            let mut desc = TlsSecBufferDesc { ver: 0, n: 4, bufs: bufs.as_mut_ptr() };
            if EncryptMessage(&c.ctx, 0, &mut desc, 0) != 0 {
                return serp_err("OSError", "socket error".into());
            }
            let total = (bufs[0].cb + bufs[1].cb + bufs[2].cb) as usize;
            if let Err(e) = c.tcp.write_all(&buf[..total]) {
                return Err(sock_io_err(&e));
            }
            off += n;
        }
        Ok(())
    }
}

#[cfg(unix)]
struct TlsApi {
    tls_client_method: unsafe extern "C" fn() -> *const std::ffi::c_void,
    ctx_new: unsafe extern "C" fn(*const std::ffi::c_void) -> *mut std::ffi::c_void,
    ctx_free: unsafe extern "C" fn(*mut std::ffi::c_void),
    ctx_set_verify: unsafe extern "C" fn(*mut std::ffi::c_void, i32, *mut std::ffi::c_void),
    ctx_set_default_verify_paths: unsafe extern "C" fn(*mut std::ffi::c_void) -> i32,
    ssl_new: unsafe extern "C" fn(*mut std::ffi::c_void) -> *mut std::ffi::c_void,
    ssl_free: unsafe extern "C" fn(*mut std::ffi::c_void),
    ssl_set_fd: unsafe extern "C" fn(*mut std::ffi::c_void, i32) -> i32,
    ssl_ctrl: unsafe extern "C" fn(*mut std::ffi::c_void, i32, i64, *mut std::ffi::c_void) -> i64,
    ssl_set1_host: unsafe extern "C" fn(*mut std::ffi::c_void, *const u8) -> i32,
    ssl_connect: unsafe extern "C" fn(*mut std::ffi::c_void) -> i32,
    ssl_read: unsafe extern "C" fn(*mut std::ffi::c_void, *mut std::ffi::c_void, i32) -> i32,
    ssl_write: unsafe extern "C" fn(*mut std::ffi::c_void, *const std::ffi::c_void, i32) -> i32,
    ssl_get_error: unsafe extern "C" fn(*const std::ffi::c_void, i32) -> i32,
    ssl_get_verify_result: unsafe extern "C" fn(*const std::ffi::c_void) -> i64,
    ssl_shutdown: unsafe extern "C" fn(*mut std::ffi::c_void) -> i32,
}

#[cfg(unix)]
static mut TLS_API: Option<TlsApi> = None;

#[cfg(target_os = "macos")]
const TLS_LIB_NAMES: [&[u8]; 4] = [
    b"libssl.3.dylib\0",
    b"/opt/homebrew/opt/openssl@3/lib/libssl.3.dylib\0",
    b"/usr/local/opt/openssl@3/lib/libssl.3.dylib\0",
    b"libssl.dylib\0",
];

#[cfg(all(unix, not(target_os = "macos")))]
const TLS_LIB_NAMES: [&[u8]; 3] = [b"libssl.so.3\0", b"libssl.so.1.1\0", b"libssl.so\0"];

#[cfg(unix)]
unsafe fn tls_sym(h: *mut std::ffi::c_void, name: &[u8]) -> SRes<*mut std::ffi::c_void> {
    let p = dlsym(h, name.as_ptr());
    if p.is_null() {
        return serp_err("OSError", "tls not available".into());
    }
    Ok(p)
}

#[cfg(unix)]
fn tls_api() -> SRes<&'static TlsApi> {
    unsafe {
        let cell = &mut *std::ptr::addr_of_mut!(TLS_API);
        if cell.is_none() {
            let mut h: *mut std::ffi::c_void = std::ptr::null_mut();
            for nm in TLS_LIB_NAMES.iter() {
                h = dlopen(nm.as_ptr(), 2);
                if !h.is_null() {
                    break;
                }
            }
            if h.is_null() {
                return serp_err("OSError", "tls not available".into());
            }
            let sym = |name: &[u8]| unsafe { tls_sym(h, name) };
            *cell = Some(TlsApi {
                tls_client_method: std::mem::transmute(sym(b"TLS_client_method\0")?),
                ctx_new: std::mem::transmute(sym(b"SSL_CTX_new\0")?),
                ctx_free: std::mem::transmute(sym(b"SSL_CTX_free\0")?),
                ctx_set_verify: std::mem::transmute(sym(b"SSL_CTX_set_verify\0")?),
                ctx_set_default_verify_paths:
                    std::mem::transmute(sym(b"SSL_CTX_set_default_verify_paths\0")?),
                ssl_new: std::mem::transmute(sym(b"SSL_new\0")?),
                ssl_free: std::mem::transmute(sym(b"SSL_free\0")?),
                ssl_set_fd: std::mem::transmute(sym(b"SSL_set_fd\0")?),
                ssl_ctrl: std::mem::transmute(sym(b"SSL_ctrl\0")?),
                ssl_set1_host: std::mem::transmute(sym(b"SSL_set1_host\0")?),
                ssl_connect: std::mem::transmute(sym(b"SSL_connect\0")?),
                ssl_read: std::mem::transmute(sym(b"SSL_read\0")?),
                ssl_write: std::mem::transmute(sym(b"SSL_write\0")?),
                ssl_get_error: std::mem::transmute(sym(b"SSL_get_error\0")?),
                ssl_get_verify_result: std::mem::transmute(sym(b"SSL_get_verify_result\0")?),
                ssl_shutdown: std::mem::transmute(sym(b"SSL_shutdown\0")?),
            });
        }
        Ok(cell.as_ref().unwrap())
    }
}

#[cfg(unix)]
struct TlsConn {
    tcp: std::net::TcpStream,
    ctx: *mut std::ffi::c_void,
    ssl: *mut std::ffi::c_void,
    eof: bool,
}

#[cfg(unix)]
impl Drop for TlsConn {
    fn drop(&mut self) {
        if let Ok(api) = tls_api() {
            unsafe {
                if !self.ssl.is_null() {
                    (api.ssl_shutdown)(self.ssl);
                    (api.ssl_free)(self.ssl);
                }
                if !self.ctx.is_null() {
                    (api.ctx_free)(self.ctx);
                }
            }
        }
    }
}

#[cfg(unix)]
fn tls_client_handshake(tcp: &mut std::net::TcpStream, host: &str, insecure: bool)
                        -> SRes<(*mut std::ffi::c_void, *mut std::ffi::c_void)> {
    use std::os::unix::io::AsRawFd;
    let api = tls_api()?;
    unsafe {
        let method = (api.tls_client_method)();
        if method.is_null() {
            return serp_err("OSError", "tls handshake failed".into());
        }
        let ctx = (api.ctx_new)(method);
        if ctx.is_null() {
            return serp_err("OSError", "tls handshake failed".into());
        }
        if !insecure {
            (api.ctx_set_default_verify_paths)(ctx);
            (api.ctx_set_verify)(ctx, 1, std::ptr::null_mut());
        }
        let ssl = (api.ssl_new)(ctx);
        if ssl.is_null() {
            (api.ctx_free)(ctx);
            return serp_err("OSError", "tls handshake failed".into());
        }
        let mut hz: Vec<u8> = host.as_bytes().to_vec();
        hz.push(0);
        // SSL_ctrl(ssl, SSL_CTRL_SET_TLSEXT_HOSTNAME=55, TLSEXT_NAMETYPE_host_name=0, host)
        (api.ssl_ctrl)(ssl, 55, 0, hz.as_mut_ptr() as *mut std::ffi::c_void);
        if !insecure {
            (api.ssl_set1_host)(ssl, hz.as_ptr());
        }
        (api.ssl_set_fd)(ssl, tcp.as_raw_fd());
        let r = (api.ssl_connect)(ssl);
        if r != 1 {
            let cert = !insecure && (api.ssl_get_verify_result)(ssl) != 0;
            (api.ssl_free)(ssl);
            (api.ctx_free)(ctx);
            if cert {
                return serp_err("OSError", "certificate verify failed".into());
            }
            return serp_err("OSError", "tls handshake failed".into());
        }
        Ok((ctx, ssl))
    }
}

#[cfg(unix)]
fn tls_read_conn(c: &mut TlsConn, maxlen: usize) -> SRes<Vec<u8>> {
    if c.eof {
        return Ok(Vec::new());
    }
    let api = tls_api()?;
    let mut buf = vec![0u8; maxlen];
    unsafe {
        let r = (api.ssl_read)(c.ssl, buf.as_mut_ptr() as *mut std::ffi::c_void,
                               maxlen as i32);
        if r > 0 {
            buf.truncate(r as usize);
            return Ok(buf);
        }
        let err = (api.ssl_get_error)(c.ssl, r);
        if err == 6 {
            c.eof = true;
            return Ok(Vec::new());
        }
        if err == 5 {
            let ose = std::io::Error::last_os_error();
            if matches!(ose.kind(), std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut) {
                return Err(sock_io_err(&ose));
            }
            c.eof = true;
            return Ok(Vec::new());
        }
        if err == 2 || err == 3 {
            return serp_err("OSError", "timed out".into());
        }
        serp_err("OSError", "socket error".into())
    }
}

#[cfg(unix)]
fn tls_write_conn(c: &mut TlsConn, data: &[u8]) -> SRes<()> {
    if data.is_empty() {
        return Ok(());
    }
    let api = tls_api()?;
    let mut off = 0usize;
    unsafe {
        while off < data.len() {
            let n = (data.len() - off).min(1 << 20) as i32;
            let r = (api.ssl_write)(c.ssl, data[off..].as_ptr() as *const std::ffi::c_void, n);
            if r <= 0 {
                let err = (api.ssl_get_error)(c.ssl, r);
                if err == 5 {
                    let ose = std::io::Error::last_os_error();
                    return Err(sock_io_err(&ose));
                }
                if err == 2 || err == 3 {
                    return serp_err("OSError", "timed out".into());
                }
                return serp_err("OSError", "socket error".into());
            }
            off += r as usize;
        }
    }
    Ok(())
}

fn serp_sock_tls_connect(host: &str, port: i64, timeout_ms: i64, insecure: i64) -> SRes<i64> {
    let addr = sock_resolve(host, port)?;
    let stream = if timeout_ms > 0 {
        std::net::TcpStream::connect_timeout(
            &addr, std::time::Duration::from_millis(timeout_ms as u64))
    } else {
        std::net::TcpStream::connect(addr)
    };
    let mut tcp = match stream {
        Ok(s) => s,
        Err(e) => return Err(sock_io_err(&e)),
    };
    if timeout_ms > 0 {
        let d = Some(std::time::Duration::from_millis(timeout_ms as u64));
        let _ = tcp.set_read_timeout(d);
        let _ = tcp.set_write_timeout(d);
    }
    #[cfg(windows)]
    {
        let (cred, ctx, sizes, extra) = tls_client_handshake(&mut tcp, host, insecure != 0)?;
        let _ = tcp.set_read_timeout(None);
        let _ = tcp.set_write_timeout(None);
        Ok(sock_push(SockRec {
            kind: SockKind::Tls(TlsConn {
                tcp, cred, ctx, sizes, enc: extra, dec: Vec::new(), eof: false,
            }),
            peer: None,
        }))
    }
    #[cfg(unix)]
    {
        let (ctx, ssl) = tls_client_handshake(&mut tcp, host, insecure != 0)?;
        let _ = tcp.set_read_timeout(None);
        let _ = tcp.set_write_timeout(None);
        Ok(sock_push(SockRec {
            kind: SockKind::Tls(TlsConn { tcp, ctx, ssl, eof: false }),
            peer: None,
        }))
    }
}

// ---------- PyVal: boxed dynamic value (immutable, refcounted Copy handle) ----------

#[derive(Clone)]
struct PVal(Rc<PValRepr>);

enum PValRepr {
    None_,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(SStr),
    Bytes(SBytes),
    List(Vec<PVal>),
    Dict(SerpDict<SStr, PVal>),
}

fn pyval_none() -> PVal { PVal(Rc::new(PValRepr::None_)) }
fn pyval_bool(b: bool) -> PVal { PVal(Rc::new(PValRepr::Bool(b))) }
fn pyval_int(i: i64) -> PVal { PVal(Rc::new(PValRepr::Int(i))) }
fn pyval_float(f: f64) -> PVal { PVal(Rc::new(PValRepr::Float(f))) }
fn pyval_str(s: SStr) -> PVal { PVal(Rc::new(PValRepr::Str(s))) }
fn pyval_bytes(b: SBytes) -> PVal { PVal(Rc::new(PValRepr::Bytes(b))) }
fn pyval_list(v: Vec<PVal>) -> PVal { PVal(Rc::new(PValRepr::List(v))) }
fn pyval_dict(d: SerpDict<SStr, PVal>) -> PVal { PVal(Rc::new(PValRepr::Dict(d))) }

fn pyval_type_name(v: &PVal) -> &'static str {
    match &*v.0 {
        PValRepr::None_ => "NoneType",
        PValRepr::Bool(_) => "bool",
        PValRepr::Int(_) => "int",
        PValRepr::Float(_) => "float",
        PValRepr::Str(_) => "str",
        PValRepr::Bytes(_) => "bytes",
        PValRepr::List(_) => "list",
        PValRepr::Dict(_) => "dict",
    }
}

fn pyval_kind(v: &PVal) -> SStr { sstr(pyval_type_name(v)) }

fn pyval_truthy(v: &PVal) -> bool {
    match &*v.0 {
        PValRepr::None_ => false,
        PValRepr::Bool(b) => *b,
        PValRepr::Int(i) => *i != 0,
        PValRepr::Float(f) => *f != 0.0,
        PValRepr::Str(s) => !s.as_str().is_empty(),
        PValRepr::Bytes(b) => !b.v.is_empty(),
        PValRepr::List(l) => !l.is_empty(),
        PValRepr::Dict(d) => !d.entries.is_empty(),
    }
}

fn pyval_eq(a: &PVal, b: &PVal) -> bool {
    match (&*a.0, &*b.0) {
        (PValRepr::None_, PValRepr::None_) => true,
        (PValRepr::Bool(x), PValRepr::Bool(y)) => x == y,
        (PValRepr::Int(x), PValRepr::Int(y)) => x == y,
        (PValRepr::Bool(x), PValRepr::Int(y)) => (*x as i64) == *y,
        (PValRepr::Int(x), PValRepr::Bool(y)) => *x == (*y as i64),
        (PValRepr::Float(x), PValRepr::Float(y)) => x == y,
        (PValRepr::Int(x), PValRepr::Float(y)) => (*x as f64) == *y,
        (PValRepr::Float(x), PValRepr::Int(y)) => *x == (*y as f64),
        (PValRepr::Bool(x), PValRepr::Float(y)) => (*x as i64 as f64) == *y,
        (PValRepr::Float(x), PValRepr::Bool(y)) => *x == (*y as i64 as f64),
        (PValRepr::Str(x), PValRepr::Str(y)) => x == y,
        (PValRepr::Bytes(x), PValRepr::Bytes(y)) => x.v == y.v,
        (PValRepr::List(x), PValRepr::List(y)) =>
            x.len() == y.len() && x.iter().zip(y.iter()).all(|(p, q)| pyval_eq(p, q)),
        (PValRepr::Dict(x), PValRepr::Dict(y)) =>
            x.entries.len() == y.entries.len() && x.entries.iter().all(|(k, v)| {
                y.entries.iter().any(|(k2, v2)| k2 == k && pyval_eq(v2, v))
            }),
        _ => false,
    }
}

impl PartialEq for PVal {
    fn eq(&self, other: &PVal) -> bool { pyval_eq(self, other) }
}

impl PyShow for PVal {
    fn py_str(&self) -> String {
        match &*self.0 {
            PValRepr::Str(s) => s.py_str(),
            _ => self.py_repr(),
        }
    }
    fn py_repr(&self) -> String {
        match &*self.0 {
            PValRepr::None_ => "None".into(),
            PValRepr::Bool(b) => b.py_repr(),
            PValRepr::Int(i) => i.py_repr(),
            PValRepr::Float(f) => f.py_repr(),
            PValRepr::Str(s) => s.py_repr(),
            PValRepr::Bytes(b) => b.py_repr(),
            PValRepr::List(l) => l.py_repr(),
            PValRepr::Dict(d) => d.py_repr(),
        }
    }
}

fn pyval_len(v: &PVal) -> SRes<i64> {
    match &*v.0 {
        PValRepr::Str(s) => Ok(py_len_str(s)),
        PValRepr::Bytes(b) => Ok(b.len_i()),
        PValRepr::List(l) => Ok(l.len() as i64),
        PValRepr::Dict(d) => Ok(d.len_i()),
        _ => serp_err("TypeError", format!("object of type '{}' has no len()", pyval_type_name(v))),
    }
}

fn pyval_getitem_i(v: &PVal, i: i64) -> SRes<PVal> {
    match &*v.0 {
        PValRepr::List(l) => {
            let n = l.len() as i64;
            let j = if i < 0 { i + n } else { i };
            if j < 0 || j >= n { return serp_err("IndexError", "list index out of range".into()); }
            Ok(l[j as usize].clone())
        }
        PValRepr::Str(s) => Ok(pyval_str(py_str_idx(s, i)?)),
        PValRepr::Bytes(b) => Ok(pyval_int(pyb_index(b, i)?)),
        PValRepr::Dict(_) => serp_err("KeyError", i.py_repr()),
        _ => serp_err("TypeError", format!("'{}' object is not subscriptable", pyval_type_name(v))),
    }
}

fn pyval_getitem_s(v: &PVal, k: &SStr) -> SRes<PVal> {
    match &*v.0 {
        PValRepr::Dict(d) => Ok(d.get_ref(k)?.clone()),
        PValRepr::List(_) => serp_err("TypeError", "list indices must be integers or slices, not str".into()),
        PValRepr::Str(_) => serp_err("TypeError", "string indices must be integers, not 'str'".into()),
        _ => serp_err("TypeError", format!("'{}' object is not subscriptable", pyval_type_name(v))),
    }
}

fn pyval_getitem_v(v: &PVal, k: &PVal) -> SRes<PVal> {
    match (&*v.0, &*k.0) {
        (_, PValRepr::Int(i)) => pyval_getitem_i(v, *i),
        (_, PValRepr::Bool(b)) => pyval_getitem_i(v, *b as i64),
        (_, PValRepr::Str(s)) => pyval_getitem_s(v, s),
        (PValRepr::Dict(_), _) => serp_err("KeyError", k.py_repr()),
        (PValRepr::List(_), _) => serp_err("TypeError",
            format!("list indices must be integers or slices, not {}", pyval_type_name(k))),
        _ => serp_err("TypeError", format!("'{}' object is not subscriptable", pyval_type_name(v))),
    }
}

fn pyval_contains(hay: &PVal, needle: &PVal) -> SRes<bool> {
    match &*hay.0 {
        PValRepr::Dict(d) => match &*needle.0 {
            PValRepr::Str(s) => Ok(d.contains(s)),
            PValRepr::List(_) | PValRepr::Dict(_) => serp_err("TypeError",
                format!("unhashable type: '{}'", pyval_type_name(needle))),
            _ => Ok(false),
        },
        PValRepr::List(l) => Ok(l.iter().any(|e| pyval_eq(e, needle))),
        PValRepr::Str(s) => match &*needle.0 {
            PValRepr::Str(n) => Ok(py_contains_str(s, n)),
            _ => serp_err("TypeError",
                format!("'in <string>' requires string as left operand, not {}", pyval_type_name(needle))),
        },
        PValRepr::Bytes(b) => match &*needle.0 {
            PValRepr::Bytes(n) => Ok(pyb_contains(b, n)),
            PValRepr::Int(i) => {
                if *i < 0 || *i > 255 { return serp_err("ValueError", "byte must be in range(0, 256)".into()); }
                Ok(b.v.contains(&(*i as u8)))
            }
            _ => serp_err("TypeError",
                format!("a bytes-like object is required, not '{}'", pyval_type_name(needle))),
        },
        _ => serp_err("TypeError", format!("argument of type '{}' is not iterable", pyval_type_name(hay))),
    }
}

fn pyval_iter(v: &PVal) -> SRes<Vec<PVal>> {
    match &*v.0 {
        PValRepr::List(l) => Ok(l.clone()),
        PValRepr::Str(s) => Ok(py_chars(s).map(pyval_str).collect()),
        PValRepr::Dict(d) => Ok(d.keys_it().map(|k| pyval_str(k.clone())).collect()),
        PValRepr::Bytes(b) => Ok(b.v.iter().map(|x| pyval_int(*x as i64)).collect()),
        _ => serp_err("TypeError", format!("'{}' object is not iterable", pyval_type_name(v))),
    }
}

fn pyval_to_int(v: &PVal) -> SRes<i64> {
    match &*v.0 {
        PValRepr::Int(i) => Ok(*i),
        PValRepr::Bool(b) => Ok(*b as i64),
        PValRepr::Float(f) => py_int_from_f(*f),
        PValRepr::Str(s) => py_int_from_str(s),
        _ => serp_err("TypeError", format!(
            "int() argument must be a string, a bytes-like object or a real number, not '{}'",
            pyval_type_name(v))),
    }
}

fn pyval_to_bytes(v: &PVal) -> SRes<SBytes> {
    match &*v.0 {
        PValRepr::Bytes(b) => Ok(b.clone()),
        PValRepr::Bool(b) => pyb_zeros(*b as i64),
        PValRepr::Int(i) => pyb_zeros(*i),
        PValRepr::List(l) => {
            let mut out: Vec<u8> = Vec::with_capacity(l.len());
            for e in l.iter() {
                match &*e.0 {
                    PValRepr::Int(i) => {
                        if *i < 0 || *i > 255 {
                            return serp_err("ValueError", "bytes must be in range(0, 256)".into());
                        }
                        out.push(*i as u8);
                    }
                    PValRepr::Bool(b) => out.push(*b as u8),
                    _ => return serp_err("TypeError", format!(
                        "'{}' object cannot be interpreted as an integer", pyval_type_name(e))),
                }
            }
            Ok(sbytes(out))
        }
        PValRepr::Str(_) => serp_err("TypeError", "string argument without an encoding".into()),
        _ => serp_err("TypeError", format!(
            "cannot convert '{}' object to bytes", pyval_type_name(v))),
    }
}

fn pyval_to_float(v: &PVal) -> SRes<f64> {
    match &*v.0 {
        PValRepr::Int(i) => Ok(*i as f64),
        PValRepr::Bool(b) => Ok(*b as i64 as f64),
        PValRepr::Float(f) => Ok(*f),
        PValRepr::Str(s) => py_float_from_str(s),
        _ => serp_err("TypeError", format!(
            "float() argument must be a string or a real number, not '{}'",
            pyval_type_name(v))),
    }
}