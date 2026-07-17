// Serpentine runtime prelude — emitted at the top of every generated program.
// Provides CPython-parity semantics: floor division, overflow traps, error
// messages (SPEC.md section 11), repr rules, and an insertion-ordered dict.
#![allow(dead_code, unused_mut, unused_variables, unused_imports, non_snake_case, unused_parens)]

use std::process;

fn serp_fatal(msg: &str) -> ! {
    eprintln!("{}", msg);
    process::exit(1);
}

// ---------- integer arithmetic with CPython semantics ----------

fn serp_add_i(a: i64, b: i64) -> i64 {
    a.checked_add(b).unwrap_or_else(|| serp_fatal("OverflowError: Serpentine int operation overflowed 64 bits"))
}
fn serp_sub_i(a: i64, b: i64) -> i64 {
    a.checked_sub(b).unwrap_or_else(|| serp_fatal("OverflowError: Serpentine int operation overflowed 64 bits"))
}
fn serp_mul_i(a: i64, b: i64) -> i64 {
    a.checked_mul(b).unwrap_or_else(|| serp_fatal("OverflowError: Serpentine int operation overflowed 64 bits"))
}
fn serp_neg_i(a: i64) -> i64 {
    a.checked_neg().unwrap_or_else(|| serp_fatal("OverflowError: Serpentine int operation overflowed 64 bits"))
}
fn serp_floordiv_i(a: i64, b: i64) -> i64 {
    if b == 0 { serp_fatal("ZeroDivisionError: integer division or modulo by zero"); }
    let q = a.checked_div(b).unwrap_or_else(|| serp_fatal("OverflowError: Serpentine int operation overflowed 64 bits"));
    if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q }
}
fn serp_mod_i(a: i64, b: i64) -> i64 {
    if b == 0 { serp_fatal("ZeroDivisionError: integer division or modulo by zero"); }
    let r = a % b;
    if r != 0 && ((r < 0) != (b < 0)) { r + b } else { r }
}
fn serp_div_i(a: i64, b: i64) -> f64 {
    if b == 0 { serp_fatal("ZeroDivisionError: division by zero"); }
    (a as f64) / (b as f64)
}
fn serp_pow_i(a: i64, b: i64) -> i64 {
    if b < 0 { serp_fatal("OverflowError: Serpentine Tier-0 int ** requires a non-negative exponent"); }
    let mut result: i64 = 1;
    let mut base = a;
    let mut exp = b;
    while exp > 0 {
        if exp & 1 == 1 { result = serp_mul_i(result, base); }
        exp >>= 1;
        if exp > 0 { base = serp_mul_i(base, base); }
    }
    result
}
fn serp_abs_i(a: i64) -> i64 {
    a.checked_abs().unwrap_or_else(|| serp_fatal("OverflowError: Serpentine int operation overflowed 64 bits"))
}

// ---------- float arithmetic with CPython semantics ----------

fn serp_div_f(a: f64, b: f64) -> f64 {
    if b == 0.0 { serp_fatal("ZeroDivisionError: float division by zero"); }
    a / b
}
fn serp_floordiv_f(a: f64, b: f64) -> f64 {
    if b == 0.0 { serp_fatal("ZeroDivisionError: float floor division"); }
    (a / b).floor()
}
fn serp_mod_f(a: f64, b: f64) -> f64 {
    if b == 0.0 { serp_fatal("ZeroDivisionError: float modulo"); }
    let r = a % b;
    if r != 0.0 && ((r < 0.0) != (b < 0.0)) { r + b } else { r }
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

fn py_str<T: PyShow>(v: T) -> String { v.py_str() }
fn py_repr<T: PyShow>(v: T) -> String { v.py_repr() }

// ---------- list operations with CPython error parity ----------

fn serp_norm_idx(i: i64, len: usize, msg: &str) -> usize {
    let n = len as i64;
    let j = if i < 0 { i + n } else { i };
    if j < 0 || j >= n { serp_fatal(msg); }
    j as usize
}
fn serp_idx<T>(v: &Vec<T>, i: i64) -> &T {
    &v[serp_norm_idx(i, v.len(), "IndexError: list index out of range")]
}
fn serp_idx_mut<T>(v: &mut Vec<T>, i: i64) -> &mut T {
    let len = v.len();
    &mut v[serp_norm_idx(i, len, "IndexError: list index out of range")]
}
fn serp_idx_set<T>(v: &mut Vec<T>, i: i64, val: T) {
    let len = v.len();
    let j = serp_norm_idx(i, len, "IndexError: list assignment index out of range");
    v[j] = val;
}
fn serp_pop<T>(v: &mut Vec<T>) -> T {
    v.pop().unwrap_or_else(|| serp_fatal("IndexError: pop from empty list"))
}
fn serp_pop_at<T>(v: &mut Vec<T>, i: i64) -> T {
    if v.is_empty() { serp_fatal("IndexError: pop from empty list"); }
    let j = serp_norm_idx(i, v.len(), "IndexError: pop index out of range");
    v.remove(j)
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

fn serp_sum_i(v: &Vec<i64>) -> i64 {
    let mut acc: i64 = 0;
    for x in v { acc = serp_add_i(acc, *x); }
    acc
}
fn serp_sum_f(v: &Vec<f64>) -> f64 {
    let mut acc: f64 = 0.0;
    for x in v { acc += *x; }
    acc
}
fn serp_min_list<T: PartialOrd + Clone>(v: &Vec<T>, name: &str) -> T {
    if v.is_empty() { serp_fatal(&format!("ValueError: {}() iterable argument is empty", name)); }
    let mut best = v[0].clone();
    for x in &v[1..] { if *x < best { best = x.clone(); } }
    best
}
fn serp_max_list<T: PartialOrd + Clone>(v: &Vec<T>, name: &str) -> T {
    if v.is_empty() { serp_fatal(&format!("ValueError: {}() iterable argument is empty", name)); }
    let mut best = v[0].clone();
    for x in &v[1..] { if *x > best { best = x.clone(); } }
    best
}
fn serp_min2<T: PartialOrd>(a: T, b: T) -> T { if b < a { b } else { a } }
fn serp_max2<T: PartialOrd>(a: T, b: T) -> T { if b > a { b } else { a } }

fn serp_range(start: i64, stop: i64, step: i64) -> Vec<i64> {
    if step == 0 { serp_fatal("ValueError: range() arg 3 must not be zero"); }
    let mut out = Vec::new();
    let mut i = start;
    if step > 0 { while i < stop { out.push(i); i += step; } }
    else { while i > stop { out.push(i); i += step; } }
    out
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
    fn get_ref(&self, k: &K) -> &V {
        for e in &self.entries {
            if &e.0 == k { return &e.1; }
        }
        serp_fatal(&format!("KeyError: {}", k.py_repr()));
    }
    fn get_mut(&mut self, k: &K) -> &mut V {
        for e in self.entries.iter_mut() {
            if &e.0 == k { return &mut e.1; }
        }
        serp_fatal(&format!("KeyError: {}", k.py_repr()));
    }
    fn contains(&self, k: &K) -> bool {
        self.entries.iter().any(|e| &e.0 == k)
    }
    fn pop_key(&mut self, k: &K) -> V {
        for (i, e) in self.entries.iter().enumerate() {
            if &e.0 == k { return self.entries.remove(i).1; }
        }
        serp_fatal(&format!("KeyError: {}", k.py_repr()));
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
fn py_split(s: &str, sep: &str) -> Vec<String> {
    if sep.is_empty() { serp_fatal("ValueError: empty separator"); }
    s.split(sep).map(String::from).collect()
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

fn py_int_from_str(s: &str) -> i64 {
    let t = s.trim();
    t.parse::<i64>().unwrap_or_else(|_| {
        serp_fatal(&format!("ValueError: invalid literal for int() with base 10: {}",
                            s.to_string().py_repr()))
    })
}
fn py_int_from_f(f: f64) -> i64 {
    if f.is_nan() { serp_fatal("ValueError: cannot convert float NaN to integer"); }
    if f.is_infinite() { serp_fatal("OverflowError: cannot convert float infinity to integer"); }
    let t = f.trunc();
    if t < (i64::MIN as f64) || t > (i64::MAX as f64) {
        serp_fatal("OverflowError: Serpentine int operation overflowed 64 bits");
    }
    t as i64
}
fn py_float_from_str(s: &str) -> f64 {
    let t = s.trim();
    t.parse::<f64>().unwrap_or_else(|_| {
        serp_fatal(&format!("ValueError: could not convert string to float: {}",
                            s.to_string().py_repr()))
    })
}
fn serp_input() -> String {
    use std::io::BufRead;
    let mut line = String::new();
    let n = std::io::stdin().lock().read_line(&mut line)
        .unwrap_or_else(|_| serp_fatal("EOFError: EOF when reading a line"));
    if n == 0 { serp_fatal("EOFError: EOF when reading a line"); }
    if line.ends_with('\n') { line.pop(); if line.ends_with('\r') { line.pop(); } }
    line
}
