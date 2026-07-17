// Serpentine runtime prelude — emitted at the top of every generated program.
// Provides CPython-parity semantics: floor division, overflow traps, error
// messages (SPEC.md section 11), repr rules, and an insertion-ordered dict.
// Phase 2: fatal runtime errors are ERROR VALUES (SerpErr), not aborts, so
// try/except can catch them (DECISIONS.md D1).
#![allow(dead_code, unused_mut, unused_variables, unused_imports, non_snake_case, unused_parens, non_camel_case_types, unreachable_code, unused_labels)]

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
        self.kind == class
    }
}

type SRes<T> = Result<T, SerpErr>;

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
impl PyShow for String {
    fn py_str(&self) -> String { self.clone() }
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

fn serp_range(start: i64, stop: i64, step: i64) -> SRes<Vec<i64>> {
    if step == 0 { return serp_err("ValueError", "range() arg 3 must not be zero".into()); }
    let mut out = Vec::new();
    let mut i = start;
    if step > 0 { while i < stop { out.push(i); i += step; } }
    else { while i > stop { out.push(i); i += step; } }
    Ok(out)
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

fn py_len_str(s: &str) -> i64 { s.chars().count() as i64 }
fn py_split_ws(s: &str) -> Vec<String> { s.split_whitespace().map(String::from).collect() }
fn py_split(s: &str, sep: &str) -> SRes<Vec<String>> {
    if sep.is_empty() { return serp_err("ValueError", "empty separator".into()); }
    Ok(s.split(sep).map(String::from).collect())
}
fn py_join(sep: &str, v: &Vec<String>) -> String { v.join(sep) }
fn py_strip(s: &str) -> String { s.trim().to_string() }
fn py_lstrip(s: &str) -> String { s.trim_start().to_string() }
fn py_rstrip(s: &str) -> String { s.trim_end().to_string() }
fn py_upper(s: &str) -> String { s.to_uppercase() }
fn py_lower(s: &str) -> String { s.to_lowercase() }
fn py_startswith(s: &str, p: &str) -> bool { s.starts_with(p) }
fn py_endswith(s: &str, p: &str) -> bool { s.ends_with(p) }
fn py_find(s: &str, sub: &str) -> i64 {
    match s.find(sub) {
        Some(byte_idx) => s[..byte_idx].chars().count() as i64,
        None => -1,
    }
}
fn py_replace(s: &str, from: &str, to: &str) -> String { s.replace(from, to) }
fn py_contains_str(hay: &str, needle: &str) -> bool { hay.contains(needle) }

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
fn serp_input() -> SRes<String> {
    use std::io::BufRead;
    let mut line = String::new();
    let n = std::io::stdin().lock().read_line(&mut line)
        .map_err(|_| SerpErr::new("EOFError", "EOF when reading a line".into()))?;
    if n == 0 { return serp_err("EOFError", "EOF when reading a line".into()); }
    if line.ends_with('\n') { line.pop(); if line.ends_with('\r') { line.pop(); } }
    Ok(line)
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
        "r" => (true, false, false, false, false),
        "w" => (false, true, false, true, true),
        "a" => (false, true, true, true, false),
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
    fn read_all(&mut self) -> SRes<String> {
        use std::io::Read;
        if !self.readable { return serp_err("io.UnsupportedOperation", "not readable".into()); }
        let f = self.inner.as_mut().ok_or_else(|| SerpErr::new("ValueError",
            "I/O operation on closed file.".into()))?;
        let mut s = String::new();
        f.read_to_string(&mut s).map_err(|e| SerpErr::new("OSError", format!("{}", e)))?;
        Ok(s)
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

// ---------- sys ----------

fn serp_argv() -> Vec<String> {
    std::env::args().collect()
}
