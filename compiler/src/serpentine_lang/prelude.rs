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

// ---------- threads (DECISIONS.md D9: Send-checked spawn/join) ----------

pub struct SJoin<T>(pub RefCell<Option<std::thread::JoinHandle<SRes<T>>>>);

const SERP_STACK: usize = 256 << 20;

fn serp_thread_spawn<T, F>(f: F) -> std::thread::JoinHandle<T>
where T: Send + 'static, F: FnOnce() -> T + Send + 'static {
    std::thread::Builder::new().stack_size(SERP_STACK).spawn(f).expect("failed to spawn thread")
}

fn serp_spawn<T, F>(f: F) -> SJoin<T>
where T: Send + 'static, F: FnOnce() -> SRes<T> + Send + 'static {
    SJoin(RefCell::new(Some(serp_thread_spawn(f))))
}

fn serp_join<T>(h: &SJoin<T>) -> SRes<T> {
    let taken = h.0.borrow_mut().take();
    match taken {
        None => Err(SerpErr::new("ValueError", "thread already joined".to_string())),
        Some(j) => match j.join() {
            Ok(r) => r,
            Err(_) => Err(SerpErr::new("RuntimeError", "thread panicked".to_string())),
        },
    }
}

fn send_str(s: &SStr) -> String { s.as_str().to_string() }
fn recv_str(s: String) -> SStr { sstring(s) }

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
    use std::io::Write;
    let _ = std::io::stdout().flush();
    let frames = serp_tb_take();
    if !frames.is_empty() {
        let mut out = String::from("Traceback (most recent call last):\n");
        for (file, line, func) in frames.iter().rev() {
            out.push_str(&format!("  File \"{}\", line {}, in {}\n", file, line, func));
        }
        eprint!("{}", out);
    }
    eprintln!("{}", e.display());
    process::exit(1);
}

std::thread_local! {
    static SERP_TB: RefCell<Vec<(String, i64, String)>> = RefCell::new(Vec::new());
}

fn serp_tb_push(file: &str, line: i64, func: &str) {
    SERP_TB.with(|t| {
        let mut t = t.borrow_mut();
        if let Some(last) = t.last_mut() {
            if last.2 == func && last.0 == file {
                return;
            }
        }
        if t.len() < 200 {
            t.push((file.to_string(), line, func.to_string()));
        }
    });
}

fn serp_tb_clear() {
    SERP_TB.with(|t| t.borrow_mut().clear());
}

fn serp_tb_take() -> Vec<(String, i64, String)> {
    SERP_TB.with(|t| std::mem::take(&mut *t.borrow_mut()))
}

#[inline]
fn serp_tr<T>(r: SRes<T>, file: &str, line: i64, func: &str) -> SRes<T> {
    if r.is_err() {
        serp_tb_push(file, line, func);
    }
    r
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
                c if (c as u32) < 0x20 || (c as u32) == 0x7f
                    || ((c as u32) >= 0x80 && (c as u32) <= 0xa0) || (c as u32) == 0xad =>
                    out.push_str(&format!("\\x{:02x}", c as u32)),
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

// ---------- insertion-ordered set (docs/spec.md D20) ----------

#[derive(Clone)]
struct SerpSet<E> {
    items: Vec<E>,
}

impl<E: PartialEq + Clone + PyShow> SerpSet<E> {
    fn new() -> Self { SerpSet { items: Vec::new() } }
    fn add(&mut self, e: E) {
        if !self.items.iter().any(|x| x == &e) { self.items.push(e); }
    }
    fn discard(&mut self, e: &E) {
        if let Some(i) = self.items.iter().position(|x| x == e) { self.items.remove(i); }
    }
    fn remove(&mut self, e: &E) -> SRes<()> {
        match self.items.iter().position(|x| x == e) {
            Some(i) => { self.items.remove(i); Ok(()) }
            None => serp_err("KeyError", e.py_repr()),
        }
    }
    fn take(&mut self) -> SRes<E> {
        if self.items.is_empty() { return serp_err("KeyError", "pop from an empty set".to_string()); }
        Ok(self.items.remove(0))
    }
    fn clear(&mut self) { self.items.clear(); }
    fn contains(&self, e: &E) -> bool { self.items.iter().any(|x| x == e) }
    fn len_i(&self) -> i64 { self.items.len() as i64 }
    fn iter_it(&self) -> impl Iterator<Item = &E> { self.items.iter() }
    fn union(&self, other: &Self) -> Self {
        let mut out = self.clone();
        for e in other.items.iter() { out.add(e.clone()); }
        out
    }
    fn intersection(&self, other: &Self) -> Self {
        let mut out = SerpSet::new();
        for e in self.items.iter() { if other.contains(e) { out.items.push(e.clone()); } }
        out
    }
    fn difference(&self, other: &Self) -> Self {
        let mut out = SerpSet::new();
        for e in self.items.iter() { if !other.contains(e) { out.items.push(e.clone()); } }
        out
    }
    fn symmetric_difference(&self, other: &Self) -> Self {
        let mut out = self.difference(other);
        for e in other.items.iter() { if !self.contains(e) { out.items.push(e.clone()); } }
        out
    }
    fn update(&mut self, other: &Self) {
        for e in other.items.iter() { self.add(e.clone()); }
    }
    fn difference_update(&mut self, other: &Self) {
        self.items.retain(|x| !other.contains(x));
    }
    fn intersection_update(&mut self, other: &Self) {
        self.items.retain(|x| other.contains(x));
    }
    fn issubset(&self, other: &Self) -> bool { self.items.iter().all(|e| other.contains(e)) }
    fn issuperset(&self, other: &Self) -> bool { other.items.iter().all(|e| self.contains(e)) }
    fn isdisjoint(&self, other: &Self) -> bool { !self.items.iter().any(|e| other.contains(e)) }
    fn from_vec(v: &[E]) -> Self {
        let mut out = SerpSet::new();
        for e in v.iter() { out.add(e.clone()); }
        out
    }
}

impl<E: PartialEq> PartialEq for SerpSet<E> {
    fn eq(&self, other: &Self) -> bool {
        self.items.len() == other.items.len()
            && self.items.iter().all(|e| other.items.iter().any(|o| o == e))
    }
}

impl<E: PyShow> PyShow for SerpSet<E> {
    fn py_str(&self) -> String { self.py_repr() }
    fn py_repr(&self) -> String {
        if self.items.is_empty() { return "set()".to_string(); }
        let parts: Vec<String> = self.items.iter().map(|e| e.py_repr()).collect();
        format!("{{{}}}", parts.join(", "))
    }
}

// ---------- str operations ----------

fn py_len_str(s: &str) -> i64 {
    if s.is_ascii() { return s.len() as i64; }
    s.chars().count() as i64
}
fn py_is_space(c: char) -> bool { c.is_whitespace() || ('\x1c'..='\x1f').contains(&c) }
fn py_trim(s: &str) -> &str { s.trim_matches(py_is_space) }
fn py_split_ws(s: &str) -> Vec<SStr> { s.split(py_is_space).filter(|p| !p.is_empty()).map(sstr).collect() }
fn py_split(s: &str, sep: &str) -> SRes<Vec<SStr>> {
    if sep.is_empty() { return serp_err("ValueError", "empty separator".into()); }
    Ok(s.split(sep).map(sstr).collect())
}
fn py_join(sep: &str, v: &Vec<SStr>) -> SStr {
    let parts: Vec<&str> = v.iter().map(|s| s.as_str()).collect();
    sstring(parts.join(sep))
}
fn py_strip(s: &str) -> SStr { sstr(py_trim(s)) }
fn py_lstrip(s: &str) -> SStr { sstr(s.trim_start_matches(py_is_space)) }
fn py_rstrip(s: &str) -> SStr { sstr(s.trim_end_matches(py_is_space)) }
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
    let t = py_trim(s);
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
    let t = py_trim(s);
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
        if c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\x0b' || c == '\x0c' {
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

fn hash_by_name(name: &str, data: &[u8]) -> SRes<Vec<u8>> {
    match name.to_ascii_lowercase().as_str() {
        "sha256" => Ok(sha256_digest(data).to_vec()),
        "sha1" => Ok(sha1_digest(data).to_vec()),
        "md5" => Ok(md5_digest(data).to_vec()),
        _ => serp_err("ValueError", format!("unsupported hash type {}", name)),
    }
}

fn hmac_raw(name: &str, key: &[u8], msg: &[u8]) -> SRes<Vec<u8>> {
    let mut k = if key.len() > 64 { hash_by_name(name, key)? } else { hash_by_name(name, b"")?; key.to_vec() };
    k.resize(64, 0);
    let mut inner: Vec<u8> = k.iter().map(|b| b ^ 0x36).collect();
    inner.extend_from_slice(msg);
    let ih = hash_by_name(name, &inner)?;
    let mut outer: Vec<u8> = k.iter().map(|b| b ^ 0x5c).collect();
    outer.extend_from_slice(&ih);
    hash_by_name(name, &outer)
}

fn serp_hmac_digest(name: &str, key: &SBytes, msg: &SBytes) -> SRes<SBytes> {
    Ok(sbytes(hmac_raw(name, &key.v, &msg.v)?))
}

fn serp_pbkdf2(name: &str, pw: &SBytes, salt: &SBytes, iters: i64, dklen: i64) -> SRes<SBytes> {
    if iters < 1 {
        return serp_err("ValueError", "iteration value must be greater than 0.".into());
    }
    let hlen = hash_by_name(name, b"")?.len() as i64;
    let want = if dklen <= 0 { hlen } else { dklen };
    let mut out: Vec<u8> = Vec::with_capacity(want as usize);
    let mut block: u32 = 1;
    while (out.len() as i64) < want {
        let mut s = salt.v.to_vec();
        s.extend_from_slice(&block.to_be_bytes());
        let mut u = hmac_raw(name, &pw.v, &s)?;
        let mut t = u.clone();
        for _ in 1..iters {
            u = hmac_raw(name, &pw.v, &u)?;
            for (a, b) in t.iter_mut().zip(u.iter()) {
                *a ^= *b;
            }
        }
        out.extend_from_slice(&t);
        block += 1;
    }
    out.truncate(want as usize);
    Ok(sbytes(out))
}

fn serp_compare_digest(a: &SBytes, b: &SBytes) -> bool {
    let mut diff: u8 = if a.v.len() == b.v.len() { 0 } else { 1 };
    let n = a.v.len().max(b.v.len());
    for i in 0..n {
        let x = if i < a.v.len() { a.v[i] } else { 0 };
        let y = if i < b.v.len() { b.v[i] } else { 0 };
        diff |= x ^ y;
    }
    diff == 0
}

// Blowfish P-array (18) then S-boxes (4x256): the fractional hex digits of pi.
const BF_INIT: [u32; 1042] = [
    0x243f6a88, 0x85a308d3, 0x13198a2e, 0x03707344, 0xa4093822, 0x299f31d0, 0x082efa98, 0xec4e6c89,
    0x452821e6, 0x38d01377, 0xbe5466cf, 0x34e90c6c, 0xc0ac29b7, 0xc97c50dd, 0x3f84d5b5, 0xb5470917,
    0x9216d5d9, 0x8979fb1b, 0xd1310ba6, 0x98dfb5ac, 0x2ffd72db, 0xd01adfb7, 0xb8e1afed, 0x6a267e96,
    0xba7c9045, 0xf12c7f99, 0x24a19947, 0xb3916cf7, 0x0801f2e2, 0x858efc16, 0x636920d8, 0x71574e69,
    0xa458fea3, 0xf4933d7e, 0x0d95748f, 0x728eb658, 0x718bcd58, 0x82154aee, 0x7b54a41d, 0xc25a59b5,
    0x9c30d539, 0x2af26013, 0xc5d1b023, 0x286085f0, 0xca417918, 0xb8db38ef, 0x8e79dcb0, 0x603a180e,
    0x6c9e0e8b, 0xb01e8a3e, 0xd71577c1, 0xbd314b27, 0x78af2fda, 0x55605c60, 0xe65525f3, 0xaa55ab94,
    0x57489862, 0x63e81440, 0x55ca396a, 0x2aab10b6, 0xb4cc5c34, 0x1141e8ce, 0xa15486af, 0x7c72e993,
    0xb3ee1411, 0x636fbc2a, 0x2ba9c55d, 0x741831f6, 0xce5c3e16, 0x9b87931e, 0xafd6ba33, 0x6c24cf5c,
    0x7a325381, 0x28958677, 0x3b8f4898, 0x6b4bb9af, 0xc4bfe81b, 0x66282193, 0x61d809cc, 0xfb21a991,
    0x487cac60, 0x5dec8032, 0xef845d5d, 0xe98575b1, 0xdc262302, 0xeb651b88, 0x23893e81, 0xd396acc5,
    0x0f6d6ff3, 0x83f44239, 0x2e0b4482, 0xa4842004, 0x69c8f04a, 0x9e1f9b5e, 0x21c66842, 0xf6e96c9a,
    0x670c9c61, 0xabd388f0, 0x6a51a0d2, 0xd8542f68, 0x960fa728, 0xab5133a3, 0x6eef0b6c, 0x137a3be4,
    0xba3bf050, 0x7efb2a98, 0xa1f1651d, 0x39af0176, 0x66ca593e, 0x82430e88, 0x8cee8619, 0x456f9fb4,
    0x7d84a5c3, 0x3b8b5ebe, 0xe06f75d8, 0x85c12073, 0x401a449f, 0x56c16aa6, 0x4ed3aa62, 0x363f7706,
    0x1bfedf72, 0x429b023d, 0x37d0d724, 0xd00a1248, 0xdb0fead3, 0x49f1c09b, 0x075372c9, 0x80991b7b,
    0x25d479d8, 0xf6e8def7, 0xe3fe501a, 0xb6794c3b, 0x976ce0bd, 0x04c006ba, 0xc1a94fb6, 0x409f60c4,
    0x5e5c9ec2, 0x196a2463, 0x68fb6faf, 0x3e6c53b5, 0x1339b2eb, 0x3b52ec6f, 0x6dfc511f, 0x9b30952c,
    0xcc814544, 0xaf5ebd09, 0xbee3d004, 0xde334afd, 0x660f2807, 0x192e4bb3, 0xc0cba857, 0x45c8740f,
    0xd20b5f39, 0xb9d3fbdb, 0x5579c0bd, 0x1a60320a, 0xd6a100c6, 0x402c7279, 0x679f25fe, 0xfb1fa3cc,
    0x8ea5e9f8, 0xdb3222f8, 0x3c7516df, 0xfd616b15, 0x2f501ec8, 0xad0552ab, 0x323db5fa, 0xfd238760,
    0x53317b48, 0x3e00df82, 0x9e5c57bb, 0xca6f8ca0, 0x1a87562e, 0xdf1769db, 0xd542a8f6, 0x287effc3,
    0xac6732c6, 0x8c4f5573, 0x695b27b0, 0xbbca58c8, 0xe1ffa35d, 0xb8f011a0, 0x10fa3d98, 0xfd2183b8,
    0x4afcb56c, 0x2dd1d35b, 0x9a53e479, 0xb6f84565, 0xd28e49bc, 0x4bfb9790, 0xe1ddf2da, 0xa4cb7e33,
    0x62fb1341, 0xcee4c6e8, 0xef20cada, 0x36774c01, 0xd07e9efe, 0x2bf11fb4, 0x95dbda4d, 0xae909198,
    0xeaad8e71, 0x6b93d5a0, 0xd08ed1d0, 0xafc725e0, 0x8e3c5b2f, 0x8e7594b7, 0x8ff6e2fb, 0xf2122b64,
    0x8888b812, 0x900df01c, 0x4fad5ea0, 0x688fc31c, 0xd1cff191, 0xb3a8c1ad, 0x2f2f2218, 0xbe0e1777,
    0xea752dfe, 0x8b021fa1, 0xe5a0cc0f, 0xb56f74e8, 0x18acf3d6, 0xce89e299, 0xb4a84fe0, 0xfd13e0b7,
    0x7cc43b81, 0xd2ada8d9, 0x165fa266, 0x80957705, 0x93cc7314, 0x211a1477, 0xe6ad2065, 0x77b5fa86,
    0xc75442f5, 0xfb9d35cf, 0xebcdaf0c, 0x7b3e89a0, 0xd6411bd3, 0xae1e7e49, 0x00250e2d, 0x2071b35e,
    0x226800bb, 0x57b8e0af, 0x2464369b, 0xf009b91e, 0x5563911d, 0x59dfa6aa, 0x78c14389, 0xd95a537f,
    0x207d5ba2, 0x02e5b9c5, 0x83260376, 0x6295cfa9, 0x11c81968, 0x4e734a41, 0xb3472dca, 0x7b14a94a,
    0x1b510052, 0x9a532915, 0xd60f573f, 0xbc9bc6e4, 0x2b60a476, 0x81e67400, 0x08ba6fb5, 0x571be91f,
    0xf296ec6b, 0x2a0dd915, 0xb6636521, 0xe7b9f9b6, 0xff34052e, 0xc5855664, 0x53b02d5d, 0xa99f8fa1,
    0x08ba4799, 0x6e85076a, 0x4b7a70e9, 0xb5b32944, 0xdb75092e, 0xc4192623, 0xad6ea6b0, 0x49a7df7d,
    0x9cee60b8, 0x8fedb266, 0xecaa8c71, 0x699a17ff, 0x5664526c, 0xc2b19ee1, 0x193602a5, 0x75094c29,
    0xa0591340, 0xe4183a3e, 0x3f54989a, 0x5b429d65, 0x6b8fe4d6, 0x99f73fd6, 0xa1d29c07, 0xefe830f5,
    0x4d2d38e6, 0xf0255dc1, 0x4cdd2086, 0x8470eb26, 0x6382e9c6, 0x021ecc5e, 0x09686b3f, 0x3ebaefc9,
    0x3c971814, 0x6b6a70a1, 0x687f3584, 0x52a0e286, 0xb79c5305, 0xaa500737, 0x3e07841c, 0x7fdeae5c,
    0x8e7d44ec, 0x5716f2b8, 0xb03ada37, 0xf0500c0d, 0xf01c1f04, 0x0200b3ff, 0xae0cf51a, 0x3cb574b2,
    0x25837a58, 0xdc0921bd, 0xd19113f9, 0x7ca92ff6, 0x94324773, 0x22f54701, 0x3ae5e581, 0x37c2dadc,
    0xc8b57634, 0x9af3dda7, 0xa9446146, 0x0fd0030e, 0xecc8c73e, 0xa4751e41, 0xe238cd99, 0x3bea0e2f,
    0x3280bba1, 0x183eb331, 0x4e548b38, 0x4f6db908, 0x6f420d03, 0xf60a04bf, 0x2cb81290, 0x24977c79,
    0x5679b072, 0xbcaf89af, 0xde9a771f, 0xd9930810, 0xb38bae12, 0xdccf3f2e, 0x5512721f, 0x2e6b7124,
    0x501adde6, 0x9f84cd87, 0x7a584718, 0x7408da17, 0xbc9f9abc, 0xe94b7d8c, 0xec7aec3a, 0xdb851dfa,
    0x63094366, 0xc464c3d2, 0xef1c1847, 0x3215d908, 0xdd433b37, 0x24c2ba16, 0x12a14d43, 0x2a65c451,
    0x50940002, 0x133ae4dd, 0x71dff89e, 0x10314e55, 0x81ac77d6, 0x5f11199b, 0x043556f1, 0xd7a3c76b,
    0x3c11183b, 0x5924a509, 0xf28fe6ed, 0x97f1fbfa, 0x9ebabf2c, 0x1e153c6e, 0x86e34570, 0xeae96fb1,
    0x860e5e0a, 0x5a3e2ab3, 0x771fe71c, 0x4e3d06fa, 0x2965dcb9, 0x99e71d0f, 0x803e89d6, 0x5266c825,
    0x2e4cc978, 0x9c10b36a, 0xc6150eba, 0x94e2ea78, 0xa5fc3c53, 0x1e0a2df4, 0xf2f74ea7, 0x361d2b3d,
    0x1939260f, 0x19c27960, 0x5223a708, 0xf71312b6, 0xebadfe6e, 0xeac31f66, 0xe3bc4595, 0xa67bc883,
    0xb17f37d1, 0x018cff28, 0xc332ddef, 0xbe6c5aa5, 0x65582185, 0x68ab9802, 0xeecea50f, 0xdb2f953b,
    0x2aef7dad, 0x5b6e2f84, 0x1521b628, 0x29076170, 0xecdd4775, 0x619f1510, 0x13cca830, 0xeb61bd96,
    0x0334fe1e, 0xaa0363cf, 0xb5735c90, 0x4c70a239, 0xd59e9e0b, 0xcbaade14, 0xeecc86bc, 0x60622ca7,
    0x9cab5cab, 0xb2f3846e, 0x648b1eaf, 0x19bdf0ca, 0xa02369b9, 0x655abb50, 0x40685a32, 0x3c2ab4b3,
    0x319ee9d5, 0xc021b8f7, 0x9b540b19, 0x875fa099, 0x95f7997e, 0x623d7da8, 0xf837889a, 0x97e32d77,
    0x11ed935f, 0x16681281, 0x0e358829, 0xc7e61fd6, 0x96dedfa1, 0x7858ba99, 0x57f584a5, 0x1b227263,
    0x9b83c3ff, 0x1ac24696, 0xcdb30aeb, 0x532e3054, 0x8fd948e4, 0x6dbc3128, 0x58ebf2ef, 0x34c6ffea,
    0xfe28ed61, 0xee7c3c73, 0x5d4a14d9, 0xe864b7e3, 0x42105d14, 0x203e13e0, 0x45eee2b6, 0xa3aaabea,
    0xdb6c4f15, 0xfacb4fd0, 0xc742f442, 0xef6abbb5, 0x654f3b1d, 0x41cd2105, 0xd81e799e, 0x86854dc7,
    0xe44b476a, 0x3d816250, 0xcf62a1f2, 0x5b8d2646, 0xfc8883a0, 0xc1c7b6a3, 0x7f1524c3, 0x69cb7492,
    0x47848a0b, 0x5692b285, 0x095bbf00, 0xad19489d, 0x1462b174, 0x23820e00, 0x58428d2a, 0x0c55f5ea,
    0x1dadf43e, 0x233f7061, 0x3372f092, 0x8d937e41, 0xd65fecf1, 0x6c223bdb, 0x7cde3759, 0xcbee7460,
    0x4085f2a7, 0xce77326e, 0xa6078084, 0x19f8509e, 0xe8efd855, 0x61d99735, 0xa969a7aa, 0xc50c06c2,
    0x5a04abfc, 0x800bcadc, 0x9e447a2e, 0xc3453484, 0xfdd56705, 0x0e1e9ec9, 0xdb73dbd3, 0x105588cd,
    0x675fda79, 0xe3674340, 0xc5c43465, 0x713e38d8, 0x3d28f89e, 0xf16dff20, 0x153e21e7, 0x8fb03d4a,
    0xe6e39f2b, 0xdb83adf7, 0xe93d5a68, 0x948140f7, 0xf64c261c, 0x94692934, 0x411520f7, 0x7602d4f7,
    0xbcf46b2e, 0xd4a20068, 0xd4082471, 0x3320f46a, 0x43b7d4b7, 0x500061af, 0x1e39f62e, 0x97244546,
    0x14214f74, 0xbf8b8840, 0x4d95fc1d, 0x96b591af, 0x70f4ddd3, 0x66a02f45, 0xbfbc09ec, 0x03bd9785,
    0x7fac6dd0, 0x31cb8504, 0x96eb27b3, 0x55fd3941, 0xda2547e6, 0xabca0a9a, 0x28507825, 0x530429f4,
    0x0a2c86da, 0xe9b66dfb, 0x68dc1462, 0xd7486900, 0x680ec0a4, 0x27a18dee, 0x4f3ffea2, 0xe887ad8c,
    0xb58ce006, 0x7af4d6b6, 0xaace1e7c, 0xd3375fec, 0xce78a399, 0x406b2a42, 0x20fe9e35, 0xd9f385b9,
    0xee39d7ab, 0x3b124e8b, 0x1dc9faf7, 0x4b6d1856, 0x26a36631, 0xeae397b2, 0x3a6efa74, 0xdd5b4332,
    0x6841e7f7, 0xca7820fb, 0xfb0af54e, 0xd8feb397, 0x454056ac, 0xba489527, 0x55533a3a, 0x20838d87,
    0xfe6ba9b7, 0xd096954b, 0x55a867bc, 0xa1159a58, 0xcca92963, 0x99e1db33, 0xa62a4a56, 0x3f3125f9,
    0x5ef47e1c, 0x9029317c, 0xfdf8e802, 0x04272f70, 0x80bb155c, 0x05282ce3, 0x95c11548, 0xe4c66d22,
    0x48c1133f, 0xc70f86dc, 0x07f9c9ee, 0x41041f0f, 0x404779a4, 0x5d886e17, 0x325f51eb, 0xd59bc0d1,
    0xf2bcc18f, 0x41113564, 0x257b7834, 0x602a9c60, 0xdff8e8a3, 0x1f636c1b, 0x0e12b4c2, 0x02e1329e,
    0xaf664fd1, 0xcad18115, 0x6b2395e0, 0x333e92e1, 0x3b240b62, 0xeebeb922, 0x85b2a20e, 0xe6ba0d99,
    0xde720c8c, 0x2da2f728, 0xd0127845, 0x95b794fd, 0x647d0862, 0xe7ccf5f0, 0x5449a36f, 0x877d48fa,
    0xc39dfd27, 0xf33e8d1e, 0x0a476341, 0x992eff74, 0x3a6f6eab, 0xf4f8fd37, 0xa812dc60, 0xa1ebddf8,
    0x991be14c, 0xdb6e6b0d, 0xc67b5510, 0x6d672c37, 0x2765d43b, 0xdcd0e804, 0xf1290dc7, 0xcc00ffa3,
    0xb5390f92, 0x690fed0b, 0x667b9ffb, 0xcedb7d9c, 0xa091cf0b, 0xd9155ea3, 0xbb132f88, 0x515bad24,
    0x7b9479bf, 0x763bd6eb, 0x37392eb3, 0xcc115979, 0x8026e297, 0xf42e312d, 0x6842ada7, 0xc66a2b3b,
    0x12754ccc, 0x782ef11c, 0x6a124237, 0xb79251e7, 0x06a1bbe6, 0x4bfb6350, 0x1a6b1018, 0x11caedfa,
    0x3d25bdd8, 0xe2e1c3c9, 0x44421659, 0x0a121386, 0xd90cec6e, 0xd5abea2a, 0x64af674e, 0xda86a85f,
    0xbebfe988, 0x64e4c3fe, 0x9dbc8057, 0xf0f7c086, 0x60787bf8, 0x6003604d, 0xd1fd8346, 0xf6381fb0,
    0x7745ae04, 0xd736fccc, 0x83426b33, 0xf01eab71, 0xb0804187, 0x3c005e5f, 0x77a057be, 0xbde8ae24,
    0x55464299, 0xbf582e61, 0x4e58f48f, 0xf2ddfda2, 0xf474ef38, 0x8789bdc2, 0x5366f9c3, 0xc8b38e74,
    0xb475f255, 0x46fcd9b9, 0x7aeb2661, 0x8b1ddf84, 0x846a0e79, 0x915f95e2, 0x466e598e, 0x20b45770,
    0x8cd55591, 0xc902de4c, 0xb90bace1, 0xbb8205d0, 0x11a86248, 0x7574a99e, 0xb77f19b6, 0xe0a9dc09,
    0x662d09a1, 0xc4324633, 0xe85a1f02, 0x09f0be8c, 0x4a99a025, 0x1d6efe10, 0x1ab93d1d, 0x0ba5a4df,
    0xa186f20f, 0x2868f169, 0xdcb7da83, 0x573906fe, 0xa1e2ce9b, 0x4fcd7f52, 0x50115e01, 0xa70683fa,
    0xa002b5c4, 0x0de6d027, 0x9af88c27, 0x773f8641, 0xc3604c06, 0x61a806b5, 0xf0177a28, 0xc0f586e0,
    0x006058aa, 0x30dc7d62, 0x11e69ed7, 0x2338ea63, 0x53c2dd94, 0xc2c21634, 0xbbcbee56, 0x90bcb6de,
    0xebfc7da1, 0xce591d76, 0x6f05e409, 0x4b7c0188, 0x39720a3d, 0x7c927c24, 0x86e3725f, 0x724d9db9,
    0x1ac15bb4, 0xd39eb8fc, 0xed545578, 0x08fca5b5, 0xd83d7cd3, 0x4dad0fc4, 0x1e50ef5e, 0xb161e6f8,
    0xa28514d9, 0x6c51133c, 0x6fd5c7e7, 0x56e14ec4, 0x362abfce, 0xddc6c837, 0xd79a3234, 0x92638212,
    0x670efa8e, 0x406000e0, 0x3a39ce37, 0xd3faf5cf, 0xabc27737, 0x5ac52d1b, 0x5cb0679e, 0x4fa33742,
    0xd3822740, 0x99bc9bbe, 0xd5118e9d, 0xbf0f7315, 0xd62d1c7e, 0xc700c47b, 0xb78c1b6b, 0x21a19045,
    0xb26eb1be, 0x6a366eb4, 0x5748ab2f, 0xbc946e79, 0xc6a376d2, 0x6549c2c8, 0x530ff8ee, 0x468dde7d,
    0xd5730a1d, 0x4cd04dc6, 0x2939bbdb, 0xa9ba4650, 0xac9526e8, 0xbe5ee304, 0xa1fad5f0, 0x6a2d519a,
    0x63ef8ce2, 0x9a86ee22, 0xc089c2b8, 0x43242ef6, 0xa51e03aa, 0x9cf2d0a4, 0x83c061ba, 0x9be96a4d,
    0x8fe51550, 0xba645bd6, 0x2826a2f9, 0xa73a3ae1, 0x4ba99586, 0xef5562e9, 0xc72fefd3, 0xf752f7da,
    0x3f046f69, 0x77fa0a59, 0x80e4a915, 0x87b08601, 0x9b09e6ad, 0x3b3ee593, 0xe990fd5a, 0x9e34d797,
    0x2cf0b7d9, 0x022b8b51, 0x96d5ac3a, 0x017da67d, 0xd1cf3ed6, 0x7c7d2d28, 0x1f9f25cf, 0xadf2b89b,
    0x5ad6b472, 0x5a88f54c, 0xe029ac71, 0xe019a5e6, 0x47b0acfd, 0xed93fa9b, 0xe8d3c48d, 0x283b57cc,
    0xf8d56629, 0x79132e28, 0x785f0191, 0xed756055, 0xf7960e44, 0xe3d35e8c, 0x15056dd4, 0x88f46dba,
    0x03a16125, 0x0564f0bd, 0xc3eb9e15, 0x3c9057a2, 0x97271aec, 0xa93a072a, 0x1b3f6d9b, 0x1e6321f5,
    0xf59c66fb, 0x26dcf319, 0x7533d928, 0xb155fdf5, 0x03563482, 0x8aba3cbb, 0x28517711, 0xc20ad9f8,
    0xabcc5167, 0xccad925f, 0x4de81751, 0x3830dc8e, 0x379d5862, 0x9320f991, 0xea7a90c2, 0xfb3e7bce,
    0x5121ce64, 0x774fbe32, 0xa8b6e37e, 0xc3293d46, 0x48de5369, 0x6413e680, 0xa2ae0810, 0xdd6db224,
    0x69852dfd, 0x09072166, 0xb39a460a, 0x6445c0dd, 0x586cdecf, 0x1c20c8ae, 0x5bbef7dd, 0x1b588d40,
    0xccd2017f, 0x6bb4e3bb, 0xdda26a7e, 0x3a59ff45, 0x3e350a44, 0xbcb4cdd5, 0x72eacea8, 0xfa6484bb,
    0x8d6612ae, 0xbf3c6f47, 0xd29be463, 0x542f5d9e, 0xaec2771b, 0xf64e6370, 0x740e0d8d, 0xe75b1357,
    0xf8721671, 0xaf537d5d, 0x4040cb08, 0x4eb4e2cc, 0x34d2466a, 0x0115af84, 0xe1b00428, 0x95983a1d,
    0x06b89fb4, 0xce6ea048, 0x6f3f3b82, 0x3520ab82, 0x011a1d4b, 0x277227f8, 0x611560b1, 0xe7933fdc,
    0xbb3a792b, 0x344525bd, 0xa08839e1, 0x51ce794b, 0x2f32c9b7, 0xa01fbac9, 0xe01cc87e, 0xbcc7d1f6,
    0xcf0111c3, 0xa1e8aac7, 0x1a908749, 0xd44fbd9a, 0xd0dadecb, 0xd50ada38, 0x0339c32a, 0xc6913667,
    0x8df9317c, 0xe0b12b4f, 0xf79e59b7, 0x43f5bb3a, 0xf2d519ff, 0x27d9459c, 0xbf97222c, 0x15e6fc2a,
    0x0f91fc71, 0x9b941525, 0xfae59361, 0xceb69ceb, 0xc2a86459, 0x12baa8d1, 0xb6c1075e, 0xe3056a0c,
    0x10d25065, 0xcb03a442, 0xe0ec6e0e, 0x1698db3b, 0x4c98a0be, 0x3278e964, 0x9f1f9532, 0xe0d392df,
    0xd3a0342b, 0x8971f21e, 0x1b0a7441, 0x4ba3348c, 0xc5be7120, 0xc37632d8, 0xdf359f8d, 0x9b992f2e,
    0xe60b6f47, 0x0fe3f11d, 0xe54cda54, 0x1edad891, 0xce6279cf, 0xcd3e7e6f, 0x1618b166, 0xfd2c1d05,
    0x848fd2c5, 0xf6fb2299, 0xf523f357, 0xa6327623, 0x93a83531, 0x56cccd02, 0xacf08162, 0x5a75ebb5,
    0x6e163697, 0x88d273cc, 0xde966292, 0x81b949d0, 0x4c50901b, 0x71c65614, 0xe6c6c7bd, 0x327a140a,
    0x45e1d006, 0xc3f27b9a, 0xc9aa53fd, 0x62a80f00, 0xbb25bfe2, 0x35bdd2f6, 0x71126905, 0xb2040222,
    0xb6cbcf7c, 0xcd769c2b, 0x53113ec0, 0x1640e3d3, 0x38abbd60, 0x2547adf0, 0xba38209c, 0xf746ce76,
    0x77afa1c5, 0x20756060, 0x85cbfe4e, 0x8ae88dd8, 0x7aaaf9b0, 0x4cf9aa7e, 0x1948c25c, 0x02fb8a8c,
    0x01c36ae4, 0xd6ebe1f9, 0x90d4f869, 0xa65cdea0, 0x3f09252d, 0xc208e69f, 0xb74e6132, 0xce77e25b,
    0x578fdfe3, 0x3ac372e6,
];

struct Bf {
    p: [u32; 18],
    s: [[u32; 256]; 4],
}

impl Bf {
    fn new() -> Bf {
        let mut p = [0u32; 18];
        p.copy_from_slice(&BF_INIT[..18]);
        let mut s = [[0u32; 256]; 4];
        for k in 0..4 {
            s[k].copy_from_slice(&BF_INIT[18 + 256 * k..18 + 256 * (k + 1)]);
        }
        Bf { p, s }
    }

    #[inline]
    fn f(&self, x: u32) -> u32 {
        let h = self.s[0][(x >> 24) as usize].wrapping_add(self.s[1][((x >> 16) & 0xff) as usize]);
        (h ^ self.s[2][((x >> 8) & 0xff) as usize]).wrapping_add(self.s[3][(x & 0xff) as usize])
    }

    fn enc(&self, mut l: u32, mut r: u32) -> (u32, u32) {
        for i in 0..16 {
            l ^= self.p[i];
            r ^= self.f(l);
            std::mem::swap(&mut l, &mut r);
        }
        std::mem::swap(&mut l, &mut r);
        r ^= self.p[16];
        l ^= self.p[17];
        (l, r)
    }

    fn expand(&mut self, data: &[u8], key: &[u8]) {
        let mut kp = 0usize;
        for i in 0..18 {
            let mut w = 0u32;
            for _ in 0..4 {
                w = (w << 8) | key[kp] as u32;
                kp = (kp + 1) % key.len();
            }
            self.p[i] ^= w;
        }
        let mut dp = 0usize;
        let next = |dp: &mut usize| -> u32 {
            let mut w = 0u32;
            for _ in 0..4 {
                let b = if data.is_empty() { 0 } else { data[*dp] };
                w = (w << 8) | b as u32;
                if !data.is_empty() {
                    *dp = (*dp + 1) % data.len();
                }
            }
            w
        };
        let (mut l, mut r) = (0u32, 0u32);
        for i in (0..18).step_by(2) {
            l ^= next(&mut dp);
            r ^= next(&mut dp);
            let (a, b) = self.enc(l, r);
            l = a;
            r = b;
            self.p[i] = l;
            self.p[i + 1] = r;
        }
        for k in 0..4 {
            for i in (0..256).step_by(2) {
                l ^= next(&mut dp);
                r ^= next(&mut dp);
                let (a, b) = self.enc(l, r);
                l = a;
                r = b;
                self.s[k][i] = l;
                self.s[k][i + 1] = r;
            }
        }
    }
}

const BCRYPT_ALPHA: &[u8; 64] = b"./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

fn bcrypt_b64_encode(data: &[u8]) -> String {
    let a = BCRYPT_ALPHA;
    let mut out = String::new();
    let mut i = 0usize;
    let n = data.len();
    while i < n {
        let mut c1 = data[i] as usize;
        i += 1;
        out.push(a[c1 >> 2] as char);
        c1 = (c1 & 0x03) << 4;
        if i >= n {
            out.push(a[c1] as char);
            break;
        }
        let c2 = data[i] as usize;
        i += 1;
        c1 |= c2 >> 4;
        out.push(a[c1] as char);
        c1 = (c2 & 0x0f) << 2;
        if i >= n {
            out.push(a[c1] as char);
            break;
        }
        let c3 = data[i] as usize;
        i += 1;
        c1 |= c3 >> 6;
        out.push(a[c1] as char);
        out.push(a[c3 & 0x3f] as char);
    }
    out
}

fn bcrypt_b64_decode(text: &[u8], nbytes: usize) -> SRes<Vec<u8>> {
    let mut vals: Vec<u32> = Vec::with_capacity(text.len());
    for &ch in text {
        match BCRYPT_ALPHA.iter().position(|&c| c == ch) {
            Some(v) => vals.push(v as u32),
            None => return serp_err("ValueError", "Invalid salt".into()),
        }
    }
    let mut out: Vec<u8> = Vec::with_capacity(nbytes);
    let mut i = 0usize;
    while out.len() < nbytes && i + 1 < vals.len() {
        out.push((((vals[i] << 2) | (vals[i + 1] >> 4)) & 0xff) as u8);
        if out.len() >= nbytes || i + 2 >= vals.len() {
            break;
        }
        out.push((((vals[i + 1] << 4) | (vals[i + 2] >> 2)) & 0xff) as u8);
        if out.len() >= nbytes || i + 3 >= vals.len() {
            break;
        }
        out.push((((vals[i + 2] << 6) | vals[i + 3]) & 0xff) as u8);
        i += 4;
    }
    if out.len() != nbytes {
        return serp_err("ValueError", "Invalid salt".into());
    }
    Ok(out)
}

fn serp_bcrypt_hash(pw: &SBytes, setting: &str) -> SRes<SStr> {
    let st = setting.as_bytes();
    if st.len() < 29 || st[0] != b'$' || st[1] != b'2' || st[3] != b'$' || st[6] != b'$'
        || !(st[2] == b'a' || st[2] == b'b' || st[2] == b'y')
        || !st[4].is_ascii_digit() || !st[5].is_ascii_digit() {
        return serp_err("ValueError", "Invalid salt".into());
    }
    let cost = ((st[4] - b'0') * 10 + (st[5] - b'0')) as u32;
    if !(4..=31).contains(&cost) {
        return serp_err("ValueError", "Invalid salt".into());
    }
    let salt = bcrypt_b64_decode(&st[7..29], 16)?;
    let mut key = pw.v.to_vec();
    key.push(0);
    key.truncate(72);
    let mut bf = Bf::new();
    bf.expand(&salt, &key);
    for _ in 0..(1u64 << cost) {
        bf.expand(&[], &key);
        bf.expand(&[], &salt);
    }
    let magic = b"OrpheanBeholderScryDoubt";
    let mut words = [0u32; 6];
    for j in 0..6 {
        words[j] = u32::from_be_bytes([magic[4 * j], magic[4 * j + 1], magic[4 * j + 2], magic[4 * j + 3]]);
    }
    for _ in 0..64 {
        for j in (0..6).step_by(2) {
            let (a, b) = bf.enc(words[j], words[j + 1]);
            words[j] = a;
            words[j + 1] = b;
        }
    }
    let mut raw: Vec<u8> = Vec::with_capacity(24);
    for w in words.iter() {
        raw.extend_from_slice(&w.to_be_bytes());
    }
    let salt_text = std::str::from_utf8(&st[7..29]).unwrap_or("");
    Ok(sstring(format!("$2{}${:02}${}{}", st[2] as char, cost, salt_text, bcrypt_b64_encode(&raw[..23]))))
}

fn serp_bcrypt_gensalt(rounds: i64, prefix: &str) -> SRes<SStr> {
    if prefix != "2a" && prefix != "2b" {
        return serp_err("ValueError", "Supported prefixes are b'2a' or b'2b'".into());
    }
    if !(4..=31).contains(&rounds) {
        return serp_err("ValueError", "Invalid rounds".into());
    }
    let mut b = [0u8; 16];
    serp_entropy(&mut b);
    Ok(sstring(format!("${}${:02}${}", prefix, rounds, bcrypt_b64_encode(&b))))
}

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

const ZMAX_OUT: usize = 256 << 20;

std::thread_local! {
    static ZLIB_TOO_BIG: std::cell::Cell<bool> = std::cell::Cell::new(false);
}

fn inflate_raw(data: &[u8]) -> Result<Vec<u8>, ()> {
    inflate_raw_end(data).map(|(v, _)| v)
}

fn inflate_raw_end(data: &[u8]) -> Result<(Vec<u8>, usize), ()> {
    ZLIB_TOO_BIG.with(|f| f.set(false));
    inflate_raw_inner(data)
}

fn zlib_over(out: &Vec<u8>) -> Result<(), ()> {
    if out.len() > ZMAX_OUT {
        ZLIB_TOO_BIG.with(|f| f.set(true));
        return Err(());
    }
    Ok(())
}

fn inflate_raw_inner(data: &[u8]) -> Result<(Vec<u8>, usize), ()> {
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
                zlib_over(&out)?;
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
                        if out.len() & 0xffff == 0 {
                            zlib_over(&out)?;
                        }
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
                        zlib_over(&out)?;
                    }
                }
            }
            _ => return Err(()),
        }
        if bfinal == 1 {
            break;
        }
    }
    let end = br.pos - (br.bit / 8) as usize;
    Ok((out, end))
}

fn zlib_bad() -> SerpErr {
    if ZLIB_TOO_BIG.with(|f| f.get()) {
        return SerpErr::new("ValueError", "decompressed data exceeds limit (256 MiB)".into());
    }
    SerpErr::new("ValueError", "invalid compressed data".into())
}

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
    let (body, end) = match inflate_raw_end(&d[2..]) {
        Ok(v) => v,
        Err(()) => return Err(zlib_bad()),
    };
    let at = 2 + end;
    if at + 4 > d.len() {
        return Err(zlib_bad());
    }
    let want = u32::from_be_bytes([d[at], d[at + 1], d[at + 2], d[at + 3]]);
    if adler32_of(&body) != want {
        return Err(zlib_bad());
    }
    Ok(sbytes(body))
}

fn gzip_member(d: &[u8], out: &mut Vec<u8>) -> Result<usize, SerpErr> {
    if d.len() < 10 || d[0] != 0x1f || d[1] != 0x8b || d[2] != 8 {
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
    if i > d.len() {
        return Err(zlib_bad());
    }
    let (body, end) = match inflate_raw_end(&d[i..]) {
        Ok(v) => v,
        Err(()) => return Err(zlib_bad()),
    };
    let at = i + end;
    if at + 8 > d.len() {
        return Err(zlib_bad());
    }
    let want_crc = u32::from_le_bytes([d[at], d[at + 1], d[at + 2], d[at + 3]]);
    let want_len = u32::from_le_bytes([d[at + 4], d[at + 5], d[at + 6], d[at + 7]]);
    if crc32_of(&body) != want_crc || body.len() as u32 != want_len {
        return Err(zlib_bad());
    }
    if out.len() + body.len() > ZMAX_OUT {
        ZLIB_TOO_BIG.with(|f| f.set(true));
        return Err(zlib_bad());
    }
    out.extend_from_slice(&body);
    Ok(at + 8)
}

fn serp_zlib_gzip_decompress(b: &SBytes) -> SRes<SBytes> {
    let d = &b.v;
    let mut out: Vec<u8> = Vec::new();
    let mut pos = 0usize;
    loop {
        while pos < d.len() && d[pos] == 0 && pos > 0 {
            pos += 1;
        }
        if pos >= d.len() {
            return Ok(sbytes(out));
        }
        pos += gzip_member(&d[pos..], &mut out)?;
    }
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
    get_autocommit: unsafe extern "C" fn(CVoidP) -> i32,
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
                get_autocommit: sym!(b"sqlite3_get_autocommit\0"),
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

fn serp_sqlite_in_tx(h: i64) -> SRes<bool> {
    let db = sql_db(h)?;
    let api = sqlite_api()?;
    Ok(unsafe { (api.get_autocommit)(db) } == 0)
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
    // Async mode (D45): the socket is non-blocking and every would-block parks the
    // calling task on the reactor instead of blocking the thread; timeout_ms is the
    // set_timeout() value replayed as the reactor deadline (0 = none).
    aio: bool,
    timeout_ms: i64,
}

fn sock_new(kind: SockKind) -> SockRec {
    SockRec { kind, peer: None, aio: false, timeout_ms: 0 }
}

// Threads (D9): the handle table is an RwLock'd Vec of per-socket Arc<Mutex<..>>,
// so blocking I/O on one socket never holds the table lock or another socket's.
// Lookups take the table in SHARED mode: the poll loop resolves one handle per
// connection per iteration, and an exclusive lock there serialized all workers.
type SockRef = std::sync::Arc<std::sync::Mutex<SockRec>>;

static SOCKS: std::sync::RwLock<Vec<Option<SockRef>>> = std::sync::RwLock::new(Vec::new());
static SOCK_FREE: std::sync::Mutex<Vec<usize>> = std::sync::Mutex::new(Vec::new());

// Per-request the event loop resolves the same few handles over and over. Taking the
// table RwLock in read mode is still an atomic read-modify-write on ONE cache line
// shared by every worker, so per-request CPU grew with the worker count. Each thread
// therefore memoizes the handles it has resolved; a relaxed load of SOCK_EPOCH (a plain
// shared read, no RMW) tells it whether any handle has been retired since.
static SOCK_EPOCH: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

thread_local! {
    static SOCK_CACHE: std::cell::RefCell<(u64, Vec<Option<SockRef>>)> =
        std::cell::RefCell::new((0, Vec::new()));
}

fn sock_cache_sync() -> u64 {
    let ep = SOCK_EPOCH.load(std::sync::atomic::Ordering::Relaxed);
    SOCK_CACHE.with(|c| {
        let mut c = c.borrow_mut();
        if c.0 != ep {
            c.0 = ep;
            c.1.clear();
        }
    });
    ep
}

fn sock_cache_get(h: i64) -> Option<SockRef> {
    if h < 1 {
        return None;
    }
    SOCK_CACHE.with(|c| {
        let c = c.borrow();
        c.1.get(h as usize - 1).cloned().flatten()
    })
}

fn sock_cache_put(h: i64, rec: &SockRef) {
    if h < 1 {
        return;
    }
    SOCK_CACHE.with(|c| {
        let mut c = c.borrow_mut();
        let i = h as usize - 1;
        if c.1.len() <= i {
            c.1.resize(i + 1, None);
        }
        c.1[i] = Some(rec.clone());
    });
}

fn sock_cache_flush() {
    SOCK_EPOCH.fetch_add(1, std::sync::atomic::Ordering::Release);
    SOCK_CACHE.with(|c| {
        let mut c = c.borrow_mut();
        c.0 = SOCK_EPOCH.load(std::sync::atomic::Ordering::Relaxed);
        c.1.clear();
    });
}

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

// Internal marker for "the non-blocking op would block"; aio_io turns it into a
// reactor wait on async-mode sockets and into CPython's "timed out" otherwise.
const SOCK_WB_KIND: &str = "_WouldBlock";

fn sock_wb_err() -> SerpErr { SerpErr::new(SOCK_WB_KIND, "would block".to_string()) }

fn sock_io_err_wb(e: &std::io::Error) -> SerpErr {
    if e.kind() == std::io::ErrorKind::WouldBlock { sock_wb_err() } else { sock_io_err(e) }
}

// Run one socket operation, parking the current task until the fd is ready when the
// socket is in async mode and the op would block (D45).
fn aio_io<T>(h: i64, write: bool, mut f: impl FnMut(&mut SockRec) -> SRes<T>) -> SRes<T> {
    loop {
        let arc = sock_get(h)?;
        let (r, aio, tmo) = {
            let mut rec = sock_lock(&arc);
            let r = f(&mut rec);
            (r, rec.aio, rec.timeout_ms)
        };
        match r {
            Err(e) if e.kind == SOCK_WB_KIND => {
                if !aio {
                    return serp_err("OSError", "timed out".into());
                }
                let ok = serp_aio_wait_fd(h, if write { 1 } else { 0 },
                                          if tmo > 0 { tmo } else { -1 })?;
                if !ok {
                    return serp_err("OSError", "timed out".into());
                }
            }
            other => return other,
        }
    }
}

fn sock_push(rec: SockRec) -> i64 {
    let arc = std::sync::Arc::new(std::sync::Mutex::new(rec));
    let slot = {
        let mut free = SOCK_FREE.lock().unwrap_or_else(|p| p.into_inner());
        free.pop()
    };
    let mut socks = SOCKS.write().unwrap_or_else(|p| p.into_inner());
    match slot {
        Some(i) if i < socks.len() && socks[i].is_none() => {
            socks[i] = Some(arc);
            (i + 1) as i64
        }
        _ => {
            socks.push(Some(arc));
            socks.len() as i64
        }
    }
}

fn sock_get(h: i64) -> SRes<SockRef> {
    sock_cache_sync();
    if let Some(rec) = sock_cache_get(h) {
        return Ok(rec);
    }
    let socks = SOCKS.read().unwrap_or_else(|p| p.into_inner());
    if h >= 1 && (h as usize) <= socks.len() {
        if let Some(rec) = &socks[h as usize - 1] {
            let out = rec.clone();
            drop(socks);
            sock_cache_put(h, &out);
            return Ok(out);
        }
    }
    serp_err("ValueError", "invalid socket handle".into())
}

fn sock_get_many(hs: &[i64]) -> Vec<Option<SockRef>> {
    sock_cache_sync();
    let mut out: Vec<Option<SockRef>> = Vec::with_capacity(hs.len());
    let mut missing = false;
    for &h in hs {
        let hit = sock_cache_get(h);
        missing |= hit.is_none();
        out.push(hit);
    }
    if !missing {
        return out;
    }
    let socks = SOCKS.read().unwrap_or_else(|p| p.into_inner());
    let mut fresh: Vec<(i64, SockRef)> = Vec::new();
    for (k, &h) in hs.iter().enumerate() {
        if out[k].is_some() {
            continue;
        }
        if h >= 1 && (h as usize) <= socks.len() {
            if let Some(rec) = &socks[h as usize - 1] {
                fresh.push((h, rec.clone()));
                out[k] = Some(rec.clone());
            }
        }
    }
    drop(socks);
    for (h, rec) in &fresh {
        sock_cache_put(*h, rec);
    }
    out
}

fn sock_lock(arc: &SockRef) -> std::sync::MutexGuard<'_, SockRec> {
    arc.lock().unwrap_or_else(|p| p.into_inner())
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
        Ok(s) => Ok(sock_push(sock_new(SockKind::Tcp(s)))),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_listen(host: &str, port: i64) -> SRes<i64> {
    let addr = sock_resolve(host, port)?;
    match std::net::TcpListener::bind(addr) {
        Ok(l) => Ok(sock_push(sock_new(SockKind::Listener(l)))),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_accept(h: i64) -> SRes<i64> {
    let s = aio_io(h, false, |rec| match &rec.kind {
        SockKind::Listener(l) => match l.accept() {
            Ok((s, _)) => Ok(s),
            Err(e) => Err(sock_io_err_wb(&e)),
        },
        _ => serp_err("ValueError", "accept() needs a listener".into()),
    })?;
    let _ = s.set_nodelay(true);
    Ok(sock_push(sock_new(SockKind::Tcp(s))))
}

fn serp_sock_send(h: i64, data: &SBytes) -> SRes<i64> {
    use std::io::Write;
    aio_io(h, true, |rec| {
        let aio = rec.aio;
        match &mut rec.kind {
            // write_all cannot be used here: on a non-blocking socket a full send
            // buffer surfaces as WouldBlock *after* a partial write, and write_all
            // discards the count. Return what actually landed and let the caller
            // resume, matching CPython's send() contract.
            SockKind::Tcp(s) => {
                let mut sent: usize = 0;
                while sent < data.v.len() {
                    match s.write(&data.v[sent..]) {
                        Ok(0) => break,
                        Ok(n) => sent += n,
                        Err(ref e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                        Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                            if aio && sent == 0 {
                                return Err(sock_wb_err());
                            }
                            break;
                        }
                        Err(e) => {
                            if sent > 0 {
                                break;
                            }
                            return Err(sock_io_err(&e));
                        }
                    }
                }
                Ok(sent as i64)
            }
            SockKind::Tls(c) => {
                tls_write_conn(c, &data.v)?;
                Ok(data.v.len() as i64)
            }
            _ => serp_err("ValueError", "send() needs a TCP stream".into()),
        }
    })
}

fn serp_sock_send_all(h: i64, data: &SBytes, timeout_ms: i64) -> SRes<i64> {
    use std::io::Write;
    let mut sent: usize = 0;
    aio_io(h, true, |rec| {
        let raw = sock_raw(rec);
        let aio = rec.aio;
        match &mut rec.kind {
            SockKind::Tcp(s) => {
                while sent < data.v.len() {
                    match s.write(&data.v[sent..]) {
                        Ok(0) => return serp_err("OSError", "connection reset by peer".into()),
                        Ok(n) => sent += n,
                        Err(ref e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                        Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                            if aio {
                                return Err(sock_wb_err());
                            }
                            // Non-blocking socket with a full send buffer: park on
                            // POLLOUT instead of spinning. timeout_ms <= 0 waits
                            // indefinitely, matching a blocking sendall().
                            let fd = match raw {
                                Some(f) => f,
                                None => return serp_err("OSError", "timed out".into()),
                            };
                            let mut fds = [SockPollFd { fd, events: SOCK_POLL_OUT, revents: 0 }];
                            let w = if timeout_ms > 0 { timeout_ms } else { 1000 };
                            if sys_poll(&mut fds, w) <= 0 && timeout_ms > 0 {
                                return serp_err("OSError", "timed out".into());
                            }
                        }
                        Err(e) => return Err(sock_io_err(&e)),
                    }
                }
                Ok(sent as i64)
            }
            SockKind::Tls(c) => {
                tls_write_conn(c, &data.v)?;
                Ok(data.v.len() as i64)
            }
            _ => serp_err("ValueError", "sendall() needs a TCP stream".into()),
        }
    })
}

fn serp_sock_recv(h: i64, maxlen: i64) -> SRes<SBytes> {
    use std::io::Read;
    if maxlen <= 0 {
        return serp_err("ValueError", "maxlen must be positive".into());
    }
    aio_io(h, false, |rec| match &mut rec.kind {
        SockKind::Tcp(s) => {
            let mut buf = vec![0u8; maxlen as usize];
            match s.read(&mut buf) {
                Ok(n) => { buf.truncate(n); Ok(sbytes(buf)) }
                Err(e) => Err(sock_io_err_wb(&e)),
            }
        }
        SockKind::Tls(c) => Ok(sbytes(tls_read_conn(c, maxlen as usize)?)),
        _ => serp_err("ValueError", "recv() needs a TCP stream".into()),
    })
}

fn serp_sock_shutdown_write(h: i64) -> SRes<()> {
    let arc = sock_get(h)?;
    let mut rec = sock_lock(&arc);
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
    let arc = sock_get(h)?;
    let mut rec = sock_lock(&arc);
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
        Ok(()) => { rec.timeout_ms = if ms > 0 { ms } else { 0 }; Ok(()) }
        Err(e) => Err(sock_io_err(&e)),
    }
}

// Async mode (D45): non-blocking fd whose would-blocks park the current task on
// the reactor (see aio_io); the plain recv/send/accept API is unchanged.
fn serp_sock_set_async(h: i64) -> SRes<()> {
    serp_sock_set_nonblocking(h)?;
    let arc = sock_get(h)?;
    let mut rec = sock_lock(&arc);
    rec.aio = true;
    Ok(())
}

fn serp_sock_local_port(h: i64) -> SRes<i64> {
    let arc = sock_get(h)?;
    let mut rec = sock_lock(&arc);
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
    let rec = sock_get(h)?;
    {
        // A cached SockRef on another thread would otherwise keep the fd alive after
        // the table drops it, so tear the connection down explicitly.
        let r = sock_lock(&rec);
        match &r.kind {
            SockKind::Tcp(s) => {
                let _ = s.shutdown(std::net::Shutdown::Both);
            }
            SockKind::Tls(c) => {
                let _ = c.tcp.shutdown(std::net::Shutdown::Both);
            }
            _ => {}
        }
    }
    drop(rec);
    let mut socks = SOCKS.write().unwrap_or_else(|p| p.into_inner());
    socks[h as usize - 1] = None;
    drop(socks);
    let mut free = SOCK_FREE.lock().unwrap_or_else(|p| p.into_inner());
    free.push(h as usize - 1);
    drop(free);
    sock_cache_flush();
    Ok(())
}

// ---------- graceful shutdown (SIGTERM / SIGINT / console Ctrl-C) ----------
// The first signal only raises a flag that serve loops poll; a second one terminates.

static SERP_SHUTDOWN: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

#[cfg(windows)]
extern "system" fn serp_ctrl_handler(_ctrl: u32) -> i32 {
    if SERP_SHUTDOWN.swap(true, std::sync::atomic::Ordering::SeqCst) {
        return 0;
    }
    1
}

#[cfg(unix)]
extern "C" fn serp_sig_handler(_sig: i32) {
    extern "C" {
        fn _exit(code: i32) -> !;
    }
    if SERP_SHUTDOWN.swap(true, std::sync::atomic::Ordering::SeqCst) {
        unsafe { _exit(130) };
    }
}

fn serp_shutdown_install() {
    #[cfg(windows)]
    {
        #[link(name = "kernel32")]
        extern "system" {
            fn SetConsoleCtrlHandler(h: Option<extern "system" fn(u32) -> i32>, add: i32) -> i32;
        }
        unsafe { SetConsoleCtrlHandler(Some(serp_ctrl_handler), 1) };
    }
    #[cfg(unix)]
    {
        extern "C" {
            fn signal(sig: i32, handler: usize) -> usize;
        }
        unsafe {
            signal(15, serp_sig_handler as usize);
            signal(2, serp_sig_handler as usize);
        }
    }
}

fn serp_shutdown_requested() -> bool {
    SERP_SHUTDOWN.load(std::sync::atomic::Ordering::SeqCst)
}

fn serp_shutdown_request() {
    SERP_SHUTDOWN.store(true, std::sync::atomic::Ordering::SeqCst);
}

// ---------- rtlib: serp_metrics_core (process-global metric store) ----------
// Global rather than thread-local so every worker thread feeds the same /metrics.

static MX_VALS: std::sync::Mutex<std::collections::BTreeMap<String, f64>> =
    std::sync::Mutex::new(std::collections::BTreeMap::new());
static MX_META: std::sync::Mutex<std::collections::BTreeMap<String, String>> =
    std::sync::Mutex::new(std::collections::BTreeMap::new());

fn serp_mx_add(key: &str, delta: f64) {
    let mut m = MX_VALS.lock().unwrap_or_else(|p| p.into_inner());
    *m.entry(key.to_string()).or_insert(0.0) += delta;
}

fn serp_mx_set(key: &str, v: f64) {
    let mut m = MX_VALS.lock().unwrap_or_else(|p| p.into_inner());
    m.insert(key.to_string(), v);
}

fn serp_mx_get(key: &str) -> f64 {
    let m = MX_VALS.lock().unwrap_or_else(|p| p.into_inner());
    m.get(key).copied().unwrap_or(0.0)
}

fn serp_mx_meta_set(key: &str, v: &str) {
    let mut m = MX_META.lock().unwrap_or_else(|p| p.into_inner());
    m.insert(key.to_string(), v.to_string());
}

fn serp_mx_meta_get(key: &str) -> SStr {
    let m = MX_META.lock().unwrap_or_else(|p| p.into_inner());
    sstring(m.get(key).cloned().unwrap_or_default())
}

fn serp_mx_meta_add(key: &str, item: &str) -> bool {
    let mut m = MX_META.lock().unwrap_or_else(|p| p.into_inner());
    let cur = m.entry(key.to_string()).or_default();
    let present = if cur.is_empty() { false } else { cur[1..].split('\n').any(|x| x == item) };
    if present {
        return false;
    }
    cur.push('\n');
    cur.push_str(item);
    true
}

fn serp_sock_set_nonblocking(h: i64) -> SRes<()> {
    let arc = sock_get(h)?;
    let rec = sock_lock(&arc);
    let r = match &rec.kind {
        SockKind::Tcp(s) => s.set_nonblocking(true),
        SockKind::Listener(l) => l.set_nonblocking(true),
        SockKind::Udp(u) => u.set_nonblocking(true),
        SockKind::Tls(c) => c.tcp.set_nonblocking(true),
    };
    match r {
        Ok(()) => Ok(()),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_accept_nb(h: i64) -> SRes<i64> {
    let arc = sock_get(h)?;
    let accepted = {
        let rec = sock_lock(&arc);
        match &rec.kind {
            SockKind::Listener(l) => match l.accept() {
                Ok((s, _)) => Some(s),
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => None,
                Err(e) => return Err(sock_io_err(&e)),
            },
            _ => return serp_err("ValueError", "accept_nb() needs a listener".into()),
        }
    };
    match accepted {
        Some(s) => {
            let _ = s.set_nonblocking(false);
            let _ = s.set_nodelay(true);
            Ok(sock_push(sock_new(SockKind::Tcp(s))))
        }
        None => Ok(0),
    }
}

#[cfg(windows)]
#[repr(C)]
struct SockPollFd {
    fd: usize,
    events: i16,
    revents: i16,
}
#[cfg(windows)]
#[link(name = "ws2_32")]
extern "system" {
    fn WSAPoll(fds: *mut SockPollFd, n: u32, timeout: i32) -> i32;
}
#[cfg(windows)]
const SOCK_POLL_IN: i16 = 0x0100 | 0x0200; // POLLRDNORM | POLLRDBAND
#[cfg(windows)]
const SOCK_POLL_OUT: i16 = 0x0010; // POLLWRNORM
#[cfg(windows)]
fn sys_poll(fds: &mut [SockPollFd], timeout_ms: i64) -> i32 {
    unsafe { WSAPoll(fds.as_mut_ptr(), fds.len() as u32, timeout_ms.max(0) as i32) }
}
#[cfg(windows)]
fn sock_raw(rec: &SockRec) -> Option<usize> {
    use std::os::windows::io::AsRawSocket;
    match &rec.kind {
        SockKind::Tcp(s) => Some(s.as_raw_socket() as usize),
        SockKind::Listener(l) => Some(l.as_raw_socket() as usize),
        SockKind::Udp(u) => Some(u.as_raw_socket() as usize),
        SockKind::Tls(c) => Some(c.tcp.as_raw_socket() as usize),
    }
}

#[cfg(unix)]
#[repr(C)]
struct SockPollFd {
    fd: i32,
    events: i16,
    revents: i16,
}
#[cfg(unix)]
extern "C" {
    fn poll(fds: *mut SockPollFd, n: u64, timeout: i32) -> i32;
}
#[cfg(unix)]
const SOCK_POLL_IN: i16 = 0x0001; // POLLIN
#[cfg(unix)]
const SOCK_POLL_OUT: i16 = 0x0004; // POLLOUT
#[cfg(unix)]
fn sys_poll(fds: &mut [SockPollFd], timeout_ms: i64) -> i32 {
    unsafe { poll(fds.as_mut_ptr(), fds.len() as u64, timeout_ms.max(0) as i32) }
}
#[cfg(unix)]
fn sock_raw(rec: &SockRec) -> Option<i32> {
    use std::os::fd::AsRawFd;
    match &rec.kind {
        SockKind::Tcp(s) => Some(s.as_raw_fd()),
        SockKind::Listener(l) => Some(l.as_raw_fd()),
        SockKind::Udp(u) => Some(u.as_raw_fd()),
        SockKind::Tls(c) => Some(c.tcp.as_raw_fd()),
    }
}

fn serp_sock_poll_ready(packed: &SBytes, timeout_ms: i64) -> SRes<SBytes> {
    let b = &packed.v;
    let mut hs: Vec<i64> = Vec::new();
    let mut i = 0;
    while i + 8 <= b.len() {
        let mut v: i64 = 0;
        for j in (0..8).rev() {
            v = (v << 8) | (b[i + j] as i64);
        }
        hs.push(v);
        i += 8;
    }
    if hs.is_empty() {
        std::thread::sleep(std::time::Duration::from_millis(timeout_ms.max(0) as u64));
        return Ok(sbytes(Vec::new()));
    }
    let mut flags: Vec<bool> = vec![false; hs.len()];
    let mut fds: Vec<SockPollFd> = Vec::new();
    let mut fd_idx: Vec<usize> = Vec::new();
    let refs = sock_get_many(&hs);
    for (k, slot) in refs.iter().enumerate() {
        match slot {
            None => flags[k] = true,
            Some(arc) => {
                let rec = sock_lock(arc);
                let buffered = matches!(&rec.kind, SockKind::Tls(c) if tls_buffered(c));
                if buffered {
                    flags[k] = true;
                } else if let Some(fd) = sock_raw(&rec) {
                    fds.push(SockPollFd { fd, events: SOCK_POLL_IN, revents: 0 });
                    fd_idx.push(k);
                } else {
                    flags[k] = true;
                }
            }
        }
    }
    let any_instant = flags.iter().any(|&f| f);
    if !any_instant && !fds.is_empty() {
        let n = sys_poll(&mut fds, timeout_ms);
        if n > 0 {
            for (pos, &k) in fd_idx.iter().enumerate() {
                if fds[pos].revents != 0 {
                    flags[k] = true;
                }
            }
        }
    }
    let mut ready: Vec<u8> = Vec::new();
    for (k, &h) in hs.iter().enumerate() {
        if flags[k] {
            let mut v = h;
            for _ in 0..8 {
                ready.push((v & 0xff) as u8);
                v >>= 8;
            }
        }
    }
    Ok(sbytes(ready))
}

fn serp_sock_udp_bind(host: &str, port: i64) -> SRes<i64> {
    let addr = sock_resolve(host, port)?;
    match std::net::UdpSocket::bind(addr) {
        Ok(u) => Ok(sock_push(sock_new(SockKind::Udp(u)))),
        Err(e) => Err(sock_io_err(&e)),
    }
}

fn serp_sock_udp_send_to(h: i64, data: &SBytes, host: &str, port: i64) -> SRes<i64> {
    let addr = sock_resolve(host, port)?;
    let arc = sock_get(h)?;
    let mut rec = sock_lock(&arc);
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
    let arc = sock_get(h)?;
    let mut rec = sock_lock(&arc);
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
    let arc = sock_get(h)?;
    let mut rec = sock_lock(&arc);
    match &rec.peer {
        Some((host, _)) => Ok(sstring(host.clone())),
        None => serp_err("ValueError", "no datagram received yet".into()),
    }
}

fn serp_sock_udp_peer_port(h: i64) -> SRes<i64> {
    let arc = sock_get(h)?;
    let mut rec = sock_lock(&arc);
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
                Err(e) => return Err(sock_io_err_wb(&e)),
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
    ssl_pending: unsafe extern "C" fn(*const std::ffi::c_void) -> i32,
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
                ssl_pending: std::mem::transmute(sym(b"SSL_pending\0")?),
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

/// Whether a TLS connection already holds decrypted bytes a read can return without I/O.
#[cfg(unix)]
fn tls_buffered(c: &TlsConn) -> bool {
    match tls_api() {
        Ok(api) => unsafe { (api.ssl_pending)(c.ssl) > 0 },
        Err(_) => false,
    }
}

/// Whether a TLS connection already holds decrypted bytes a read can return without I/O.
#[cfg(windows)]
fn tls_buffered(c: &TlsConn) -> bool {
    !c.dec.is_empty()
}

// Exclusive access is guaranteed by the per-socket Mutex (SockRef).
#[cfg(unix)]
unsafe impl Send for TlsConn {}

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
                return Err(sock_io_err_wb(&ose));
            }
            c.eof = true;
            return Ok(Vec::new());
        }
        if err == 2 || err == 3 {
            return Err(sock_wb_err());
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
        Ok(sock_push(sock_new(SockKind::Tls(TlsConn {
            tcp, cred, ctx, sizes, enc: extra, dec: Vec::new(), eof: false,
        }))))
    }
    #[cfg(unix)]
    {
        let (ctx, ssl) = tls_client_handshake(&mut tcp, host, insecure != 0)?;
        let _ = tcp.set_read_timeout(None);
        let _ = tcp.set_write_timeout(None);
        Ok(sock_push(sock_new(SockKind::Tls(TlsConn { tcp, ctx, ssl, eof: false }))))
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
    Dict(SerpDict<PVal, PVal>),
}

fn pyval_none() -> PVal { PVal(Rc::new(PValRepr::None_)) }
fn pyval_bool(b: bool) -> PVal { PVal(Rc::new(PValRepr::Bool(b))) }
fn pyval_int(i: i64) -> PVal { PVal(Rc::new(PValRepr::Int(i))) }
fn pyval_float(f: f64) -> PVal { PVal(Rc::new(PValRepr::Float(f))) }
fn pyval_str(s: SStr) -> PVal { PVal(Rc::new(PValRepr::Str(s))) }
fn pyval_bytes(b: SBytes) -> PVal { PVal(Rc::new(PValRepr::Bytes(b))) }
fn pyval_list(v: Vec<PVal>) -> PVal { PVal(Rc::new(PValRepr::List(v))) }
fn pyval_dict(d: SerpDict<PVal, PVal>) -> PVal { PVal(Rc::new(PValRepr::Dict(d))) }

fn json_key_text(k: &PVal) -> String {
    // CPython json: str keys as-is; int/float/bool/None keys are coerced to text.
    match &*k.0 {
        PValRepr::Str(s) => s.as_str().to_string(),
        PValRepr::Bool(b) => if *b { "true".into() } else { "false".into() },
        PValRepr::None_ => "null".into(),
        PValRepr::Int(i) => i.to_string(),
        PValRepr::Float(f) => f.py_repr(),
        _ => k.py_repr(),
    }
}

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

// ---------- JSON serialization (serp-json fast path) ----------
// Byte-for-byte identical to serp_json._dump / _escape_string, but without the
// per-character Rc<str> churn that made a 28-byte response cost ~14us.

const JSON_HEX: &[u8; 16] = b"0123456789abcdef";

fn json_u4(out: &mut String, n: u32) {
    out.push_str("\\u");
    out.push(JSON_HEX[((n >> 12) & 0xf) as usize] as char);
    out.push(JSON_HEX[((n >> 8) & 0xf) as usize] as char);
    out.push(JSON_HEX[((n >> 4) & 0xf) as usize] as char);
    out.push(JSON_HEX[(n & 0xf) as usize] as char);
}

fn json_escape(out: &mut String, s: &str, ensure_ascii: bool) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            _ => {
                let n = c as u32;
                if n < 32 {
                    out.push_str("\\u00");
                    out.push(JSON_HEX[((n >> 4) & 0xf) as usize] as char);
                    out.push(JSON_HEX[(n & 0xf) as usize] as char);
                } else if n > 126 && ensure_ascii {
                    if n > 65535 {
                        let m = n - 65536;
                        json_u4(out, 55296 + (m >> 10));
                        json_u4(out, 56320 + (m & 1023));
                    } else {
                        json_u4(out, n);
                    }
                } else {
                    out.push(c);
                }
            }
        }
    }
    out.push('"');
}

fn json_float(out: &mut String, f: f64) {
    if f.is_nan() {
        out.push_str("NaN");
    } else if f.is_infinite() {
        out.push_str(if f > 0.0 { "Infinity" } else { "-Infinity" });
    } else {
        out.push_str(&py_float_repr(f));
    }
}

fn json_write(out: &mut String, v: &PVal, ensure_ascii: bool, compact: bool) -> SRes<()> {
    match &*v.0 {
        PValRepr::None_ => out.push_str("null"),
        PValRepr::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        PValRepr::Int(i) => out.push_str(&i.to_string()),
        PValRepr::Float(f) => json_float(out, *f),
        PValRepr::Str(s) => json_escape(out, s.as_str(), ensure_ascii),
        PValRepr::List(l) => {
            out.push('[');
            for (i, x) in l.iter().enumerate() {
                if i > 0 {
                    out.push_str(if compact { "," } else { ", " });
                }
                json_write(out, x, ensure_ascii, compact)?;
            }
            out.push(']');
        }
        PValRepr::Dict(d) => {
            out.push('{');
            let mut first = true;
            for (k, val) in d.items_it() {
                if !first {
                    out.push_str(if compact { "," } else { ", " });
                }
                first = false;
                json_escape(out, &json_key_text(k), ensure_ascii);
                out.push_str(if compact { ":" } else { ": " });
                json_write(out, val, ensure_ascii, compact)?;
            }
            out.push('}');
        }
        PValRepr::Bytes(_) => {
            return serp_err("TypeError",
                            "Object of type bytes is not JSON serializable".into());
        }
    }
    Ok(())
}

fn pyval_json(v: &PVal, ensure_ascii: bool, compact: bool) -> SRes<SStr> {
    let mut out = String::with_capacity(64);
    json_write(&mut out, v, ensure_ascii, compact)?;
    Ok(sstring(out))
}

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
        PValRepr::Dict(d) => Ok(d.get_ref(&pyval_int(i))?.clone()),
        _ => serp_err("TypeError", format!("'{}' object is not subscriptable", pyval_type_name(v))),
    }
}

fn pyval_getitem_s(v: &PVal, k: &SStr) -> SRes<PVal> {
    match &*v.0 {
        PValRepr::Dict(d) => Ok(d.get_ref(&pyval_str(k.clone()))?.clone()),
        PValRepr::List(_) => serp_err("TypeError", "list indices must be integers or slices, not str".into()),
        PValRepr::Str(_) => serp_err("TypeError", "string indices must be integers, not 'str'".into()),
        _ => serp_err("TypeError", format!("'{}' object is not subscriptable", pyval_type_name(v))),
    }
}

fn pyval_getitem_v(v: &PVal, k: &PVal) -> SRes<PVal> {
    match (&*v.0, &*k.0) {
        (PValRepr::Dict(_), PValRepr::List(_)) | (PValRepr::Dict(_), PValRepr::Dict(_)) =>
            serp_err("TypeError", format!("unhashable type: '{}'", pyval_type_name(k))),
        (PValRepr::Dict(d), _) => Ok(d.get_ref(k)?.clone()),
        (_, PValRepr::Int(i)) => pyval_getitem_i(v, *i),
        (_, PValRepr::Bool(b)) => pyval_getitem_i(v, *b as i64),
        (_, PValRepr::Str(s)) => pyval_getitem_s(v, s),
        (PValRepr::List(_), _) => serp_err("TypeError",
            format!("list indices must be integers or slices, not {}", pyval_type_name(k))),
        _ => serp_err("TypeError", format!("'{}' object is not subscriptable", pyval_type_name(v))),
    }
}

fn pyval_contains(hay: &PVal, needle: &PVal) -> SRes<bool> {
    match &*hay.0 {
        PValRepr::Dict(d) => match &*needle.0 {
            PValRepr::List(_) | PValRepr::Dict(_) => serp_err("TypeError",
                format!("unhashable type: '{}'", pyval_type_name(needle))),
            _ => Ok(d.contains(needle)),
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
        PValRepr::Dict(d) => Ok(d.keys_it().cloned().collect()),
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

// ---------- rtlib: serp_subprocess (std::process; error messages normalized
// identically in the CPython delegate so dual runs stay byte-identical) ----------

const SP_STDIN_PIPE: i64 = 1;
const SP_STDOUT_PIPE: i64 = 2;
const SP_STDERR_PIPE: i64 = 4;
const SP_STDERR_TO_STDOUT: i64 = 8;
const SP_SHELL: i64 = 16;
const SP_ENV: i64 = 32;
const SP_STDIN_DEVNULL: i64 = 64;
const SP_STDOUT_DEVNULL: i64 = 128;
const SP_STDERR_DEVNULL: i64 = 256;

struct SpProc {
    child: std::process::Child,
    stdin: Option<std::process::ChildStdin>,
    out_src: Option<Box<dyn std::io::Read + Send>>,
    err_src: Option<Box<dyn std::io::Read + Send>>,
    out_thread: Option<std::thread::JoinHandle<Vec<u8>>>,
    err_thread: Option<std::thread::JoinHandle<Vec<u8>>>,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    code: Option<i64>,
}

static mut SP_PROCS: Vec<Option<SpProc>> = Vec::new();

fn sp_procs() -> &'static mut Vec<Option<SpProc>> {
    unsafe { &mut *std::ptr::addr_of_mut!(SP_PROCS) }
}

fn sp_proc(h: i64) -> SRes<&'static mut SpProc> {
    let v = sp_procs();
    if h < 1 || h as usize > v.len() {
        return serp_err("ValueError", "invalid process handle".into());
    }
    match &mut v[h as usize - 1] {
        Some(p) => Ok(p),
        None => serp_err("ValueError", "process handle already closed".into()),
    }
}

#[cfg(windows)]
fn sp_pipe() -> SRes<(std::fs::File, std::fs::File)> {
    use std::os::windows::io::FromRawHandle;
    #[repr(C)]
    struct SecAttr { n: u32, d: *mut std::ffi::c_void, inherit: i32 }
    extern "system" {
        fn CreatePipe(r: *mut *mut std::ffi::c_void, w: *mut *mut std::ffi::c_void,
                      sa: *const SecAttr, size: u32) -> i32;
    }
    let sa = SecAttr { n: 24, d: std::ptr::null_mut(), inherit: 0 };
    let mut r: *mut std::ffi::c_void = std::ptr::null_mut();
    let mut w: *mut std::ffi::c_void = std::ptr::null_mut();
    if unsafe { CreatePipe(&mut r, &mut w, &sa, 0) } == 0 {
        return serp_err("OSError", "could not create pipe".into());
    }
    Ok(unsafe { (std::fs::File::from_raw_handle(r), std::fs::File::from_raw_handle(w)) })
}

#[cfg(not(windows))]
fn sp_pipe() -> SRes<(std::fs::File, std::fs::File)> {
    use std::os::unix::io::FromRawFd;
    extern "C" {
        fn pipe(fds: *mut i32) -> i32;
        fn fcntl(fd: i32, cmd: i32, arg: i32) -> i32;
    }
    let mut fds = [0i32; 2];
    if unsafe { pipe(fds.as_mut_ptr()) } != 0 {
        return serp_err("OSError", "could not create pipe".into());
    }
    unsafe {
        fcntl(fds[0], 2, 1);
        fcntl(fds[1], 2, 1);
        Ok((std::fs::File::from_raw_fd(fds[0]), std::fs::File::from_raw_fd(fds[1])))
    }
}

fn sp_parent_stdout() -> SRes<std::process::Stdio> {
    #[cfg(windows)]
    {
        use std::os::windows::io::AsHandle;
        match std::io::stdout().as_handle().try_clone_to_owned() {
            Ok(h) => Ok(std::process::Stdio::from(h)),
            Err(_) => serp_err("OSError", "could not duplicate stdout".into()),
        }
    }
    #[cfg(not(windows))]
    {
        use std::os::unix::io::AsFd;
        match std::io::stdout().as_fd().try_clone_to_owned() {
            Ok(h) => Ok(std::process::Stdio::from(h)),
            Err(_) => serp_err("OSError", "could not duplicate stdout".into()),
        }
    }
}

fn sp_exit_code(st: std::process::ExitStatus) -> i64 {
    #[cfg(windows)]
    {
        st.code().map(|c| (c as u32) as i64).unwrap_or(-1)
    }
    #[cfg(not(windows))]
    {
        use std::os::unix::process::ExitStatusExt;
        match st.code() {
            Some(c) => c as i64,
            None => -(st.signal().unwrap_or(0) as i64),
        }
    }
}

fn serp_sp_spawn(argv: &str, cwd: &str, env: &str, flags: i64) -> SRes<i64> {
    let parts: Vec<&str> = if argv.is_empty() { Vec::new() } else { argv.split('\0').collect() };
    let mut cmd;
    if flags & SP_SHELL != 0 {
        let line = parts.join(" ");
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd = std::process::Command::new(
                std::env::var("COMSPEC").unwrap_or_else(|_| "cmd.exe".to_string()));
            cmd.raw_arg(format!("/c \"{}\"", line));
        }
        #[cfg(not(windows))]
        {
            cmd = std::process::Command::new("/bin/sh");
            cmd.arg("-c").arg(line);
        }
    } else {
        if parts.is_empty() {
            return serp_err("IndexError", "list index out of range".into());
        }
        cmd = std::process::Command::new(parts[0]);
        cmd.args(&parts[1..]);
    }
    if !cwd.is_empty() {
        cmd.current_dir(cwd);
    }
    if flags & SP_ENV != 0 {
        cmd.env_clear();
        if !env.is_empty() {
            for kv in env.split('\0') {
                if let Some((k, v)) = kv.split_once('=') {
                    cmd.env(k, v);
                }
            }
        }
    }
    if flags & SP_STDIN_PIPE != 0 {
        cmd.stdin(std::process::Stdio::piped());
    } else if flags & SP_STDIN_DEVNULL != 0 {
        cmd.stdin(std::process::Stdio::null());
    }
    let mut merged: Option<std::fs::File> = None;
    if flags & SP_STDOUT_PIPE != 0 {
        if flags & SP_STDERR_TO_STDOUT != 0 {
            let (r, w) = sp_pipe()?;
            let w2 = match w.try_clone() {
                Ok(f) => f,
                Err(_) => return serp_err("OSError", "could not duplicate pipe".into()),
            };
            cmd.stdout(std::process::Stdio::from(w));
            cmd.stderr(std::process::Stdio::from(w2));
            merged = Some(r);
        } else {
            cmd.stdout(std::process::Stdio::piped());
        }
    } else if flags & SP_STDOUT_DEVNULL != 0 {
        cmd.stdout(std::process::Stdio::null());
    }
    if merged.is_none() {
        if flags & SP_STDERR_PIPE != 0 {
            cmd.stderr(std::process::Stdio::piped());
        } else if flags & SP_STDERR_TO_STDOUT != 0 {
            cmd.stderr(sp_parent_stdout()?);
        } else if flags & SP_STDERR_DEVNULL != 0 {
            cmd.stderr(std::process::Stdio::null());
        }
    }
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            let prog = if flags & SP_SHELL != 0 { "sh".to_string() } else { parts[0].to_string() };
            return match e.kind() {
                std::io::ErrorKind::NotFound =>
                    serp_err("FileNotFoundError", format!("No such file or directory: {}", os_repr(&prog))),
                std::io::ErrorKind::PermissionDenied =>
                    serp_err("PermissionError", format!("Permission denied: {}", os_repr(&prog))),
                _ => serp_err("OSError", format!("could not start process: {}", os_repr(&prog))),
            };
        }
    };
    let stdin = child.stdin.take();
    let out_src: Option<Box<dyn std::io::Read + Send>> = match merged {
        Some(r) => Some(Box::new(r)),
        None => child.stdout.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
    };
    let err_src: Option<Box<dyn std::io::Read + Send>> =
        child.stderr.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>);
    let procs = sp_procs();
    procs.push(Some(SpProc {
        child, stdin, out_src, err_src,
        out_thread: None, err_thread: None,
        stdout: Vec::new(), stderr: Vec::new(), code: None,
    }));
    Ok(procs.len() as i64)
}

fn serp_sp_pid(h: i64) -> SRes<i64> {
    Ok(sp_proc(h)?.child.id() as i64)
}

fn sp_drain_thread(src: Box<dyn std::io::Read + Send>) -> std::thread::JoinHandle<Vec<u8>> {
    serp_thread_spawn(move || {
        use std::io::Read;
        let mut src = src;
        let mut buf = Vec::new();
        let _ = src.read_to_end(&mut buf);
        buf
    })
}

fn sp_record_exit(p: &mut SpProc, st: std::process::ExitStatus) {
    p.code = Some(sp_exit_code(st));
    if let Some(t) = p.out_thread.take() {
        p.stdout = t.join().unwrap_or_default();
    }
    if let Some(t) = p.err_thread.take() {
        p.stderr = t.join().unwrap_or_default();
    }
}

fn sp_wait_until(p: &mut SpProc, timeout_ms: i64) -> SRes<bool> {
    if p.code.is_some() {
        return Ok(true);
    }
    if timeout_ms < 0 {
        return match p.child.wait() {
            Ok(st) => { sp_record_exit(p, st); Ok(true) }
            Err(e) => serp_err("OSError", format!("wait failed: {}", e)),
        };
    }
    let deadline = std::time::Instant::now() + std::time::Duration::from_millis(timeout_ms as u64);
    loop {
        match p.child.try_wait() {
            Ok(Some(st)) => { sp_record_exit(p, st); return Ok(true); }
            Ok(None) => {}
            Err(e) => return serp_err("OSError", format!("wait failed: {}", e)),
        }
        if std::time::Instant::now() >= deadline {
            return Ok(false);
        }
        std::thread::sleep(std::time::Duration::from_millis(1));
    }
}

fn serp_sp_communicate(h: i64, input: &SBytes, has_input: i64, timeout_ms: i64) -> SRes<bool> {
    let p = sp_proc(h)?;
    if let Some(src) = p.out_src.take() {
        p.out_thread = Some(sp_drain_thread(src));
    }
    if let Some(src) = p.err_src.take() {
        p.err_thread = Some(sp_drain_thread(src));
    }
    if let Some(mut w) = p.stdin.take() {
        use std::io::Write;
        if has_input != 0 {
            let _ = w.write_all(&input.v);
        }
        let _ = w.flush();
        drop(w);
    }
    sp_wait_until(p, timeout_ms)
}

fn serp_sp_wait(h: i64, timeout_ms: i64) -> SRes<bool> {
    sp_wait_until(sp_proc(h)?, timeout_ms)
}

fn serp_sp_poll(h: i64) -> SRes<bool> {
    let p = sp_proc(h)?;
    if p.code.is_some() {
        return Ok(true);
    }
    match p.child.try_wait() {
        Ok(Some(st)) => { sp_record_exit(p, st); Ok(true) }
        Ok(None) => Ok(false),
        Err(e) => serp_err("OSError", format!("wait failed: {}", e)),
    }
}

fn serp_sp_returncode(h: i64) -> SRes<i64> {
    match sp_proc(h)?.code {
        Some(c) => Ok(c),
        None => serp_err("ValueError", "process has not exited".into()),
    }
}

fn serp_sp_stdout(h: i64) -> SRes<SBytes> {
    Ok(sbytes(sp_proc(h)?.stdout.clone()))
}

fn serp_sp_stderr(h: i64) -> SRes<SBytes> {
    Ok(sbytes(sp_proc(h)?.stderr.clone()))
}

fn serp_sp_kill(h: i64) -> SRes<()> {
    let p = sp_proc(h)?;
    if p.code.is_none() {
        let _ = p.child.kill();
    }
    Ok(())
}

fn serp_sp_terminate(h: i64) -> SRes<()> {
    let p = sp_proc(h)?;
    if p.code.is_some() {
        return Ok(());
    }
    #[cfg(windows)]
    {
        let _ = p.child.kill();
    }
    #[cfg(not(windows))]
    {
        extern "C" {
            fn kill(pid: i32, sig: i32) -> i32;
        }
        unsafe { kill(p.child.id() as i32, 15); }
    }
    Ok(())
}

fn serp_sp_free(h: i64) -> SRes<()> {
    let v = sp_procs();
    if h >= 1 && (h as usize) <= v.len() {
        v[h as usize - 1] = None;
    }
    Ok(())
}

// ---------- rtlib: serp_threading (D9 v2 — Thread objects + sync primitives) and
// serp_queue. Tables are Mutex-protected; objects are Arc so handles copied into
// other threads stay valid. Error messages mirror CPython's threading module. ----------

use std::sync::atomic::{AtomicBool, AtomicI64, Ordering as AtOrd};
use std::sync::{Arc, Condvar, Mutex};

static TH_NEXT_IDENT: AtomicI64 = AtomicI64::new(2);
static TH_MAIN_ASSIGNED: AtomicBool = AtomicBool::new(false);
static TH_ALIVE: AtomicI64 = AtomicI64::new(0);
static TH_NAME_COUNTER: AtomicI64 = AtomicI64::new(0);

thread_local! {
    static TH_IDENT: std::cell::Cell<i64> = std::cell::Cell::new(0);
    static TH_NAME: std::cell::RefCell<String> = std::cell::RefCell::new(String::new());
    static TH_TLS: std::cell::RefCell<std::collections::HashMap<String, PVal>> =
        std::cell::RefCell::new(std::collections::HashMap::new());
    static Q_LAST: std::cell::RefCell<Option<PVal>> = std::cell::RefCell::new(None);
}

fn lock_ok<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

fn th_ident() -> i64 {
    TH_IDENT.with(|c| {
        if c.get() == 0 {
            let id = if !TH_MAIN_ASSIGNED.swap(true, AtOrd::SeqCst) { 1 }
                     else { TH_NEXT_IDENT.fetch_add(1, AtOrd::SeqCst) };
            c.set(id);
            if id == 1 {
                TH_NAME.with(|n| *n.borrow_mut() = "MainThread".to_string());
            }
        }
        c.get()
    })
}

fn serp_th_ident() -> i64 { th_ident() }

fn serp_th_name() -> SStr {
    th_ident();
    TH_NAME.with(|n| sstring(n.borrow().clone()))
}

fn serp_th_active_count() -> i64 { TH_ALIVE.load(AtOrd::SeqCst) + 1 }

fn serp_th_main_ident() -> i64 { 1 }

fn serp_tls_set(key: &str, val: &PVal) {
    TH_TLS.with(|m| { m.borrow_mut().insert(key.to_string(), val.clone()); });
}

fn serp_tls_get(key: &str) -> PVal {
    TH_TLS.with(|m| m.borrow().get(key).cloned().unwrap_or_else(pyval_none))
}

fn serp_tls_has(key: &str) -> bool {
    TH_TLS.with(|m| m.borrow().contains_key(key))
}

fn serp_tls_del(key: &str) -> bool {
    TH_TLS.with(|m| m.borrow_mut().remove(key).is_some())
}

type ThreadBody = Box<dyn FnOnce() -> Result<(), (String, String)> + Send>;

struct ThreadRec {
    name: Mutex<String>,
    daemon: bool,
    ident: AtomicI64,
    started: AtomicBool,
    body: Mutex<Option<ThreadBody>>,
    handle: Mutex<Option<std::thread::JoinHandle<()>>>,
    delay_ms: i64,
    cancel_m: Mutex<bool>,
    cancel_cv: Condvar,
}

type SThread = Arc<ThreadRec>;

static TH_REGISTRY: Mutex<Vec<Arc<ThreadRec>>> = Mutex::new(Vec::new());

fn serp_thread_new(body: ThreadBody, name: Option<String>, daemon: bool, delay_ms: i64,
                   target_name: &str) -> SThread {
    let name = match name {
        Some(n) => n,
        None => {
            let n = TH_NAME_COUNTER.fetch_add(1, AtOrd::SeqCst) + 1;
            if target_name.is_empty() { format!("Thread-{}", n) }
            else { format!("Thread-{} ({})", n, target_name) }
        }
    };
    Arc::new(ThreadRec {
        name: Mutex::new(name),
        daemon,
        ident: AtomicI64::new(0),
        started: AtomicBool::new(false),
        body: Mutex::new(Some(body)),
        handle: Mutex::new(None),
        delay_ms,
        cancel_m: Mutex::new(false),
        cancel_cv: Condvar::new(),
    })
}

fn serp_thread_start(t: &SThread) -> SRes<()> {
    if t.started.swap(true, AtOrd::SeqCst) {
        return serp_err("RuntimeError", "threads can only be started once".into());
    }
    let body = match lock_ok(&t.body).take() {
        Some(b) => b,
        None => return serp_err("RuntimeError", "threads can only be started once".into()),
    };
    let ident = TH_NEXT_IDENT.fetch_add(1, AtOrd::SeqCst);
    t.ident.store(ident, AtOrd::SeqCst);
    TH_ALIVE.fetch_add(1, AtOrd::SeqCst);
    if !t.daemon {
        lock_ok(&TH_REGISTRY).push(t.clone());
    }
    let rec = t.clone();
    let mut guard = lock_ok(&t.handle);
    let h = serp_thread_spawn(move || {
        TH_IDENT.with(|c| c.set(ident));
        TH_NAME.with(|n| *n.borrow_mut() = lock_ok(&rec.name).clone());
        let mut cancelled = false;
        if rec.delay_ms > 0 {
            let deadline = std::time::Instant::now()
                + std::time::Duration::from_millis(rec.delay_ms as u64);
            let mut c = lock_ok(&rec.cancel_m);
            while !*c {
                let now = std::time::Instant::now();
                if now >= deadline { break; }
                c = rec.cancel_cv.wait_timeout(c, deadline - now)
                    .unwrap_or_else(|e| e.into_inner()).0;
            }
            cancelled = *c;
        }
        if !cancelled {
            if let Err((kind, msg)) = body() {
                eprintln!("Exception in thread {}:\n{}: {}", lock_ok(&rec.name), kind, msg);
            }
        }
        TH_ALIVE.fetch_sub(1, AtOrd::SeqCst);
    });
    *guard = Some(h);
    Ok(())
}

fn serp_thread_join(t: &SThread, timeout_ms: i64) -> SRes<()> {
    if !t.started.load(AtOrd::SeqCst) {
        return serp_err("RuntimeError", "cannot join thread before it is started".into());
    }
    if t.ident.load(AtOrd::SeqCst) == th_ident() {
        return serp_err("RuntimeError", "cannot join current thread".into());
    }
    if timeout_ms >= 0 {
        let deadline = std::time::Instant::now()
            + std::time::Duration::from_millis(timeout_ms as u64);
        loop {
            let done = match &*lock_ok(&t.handle) { Some(h) => h.is_finished(), None => true };
            if done { break; }
            if std::time::Instant::now() >= deadline { return Ok(()); }
            std::thread::sleep(std::time::Duration::from_millis(1));
        }
    }
    let h = lock_ok(&t.handle).take();
    if let Some(h) = h {
        let _ = h.join();
    }
    Ok(())
}

fn serp_thread_is_alive(t: &SThread) -> bool {
    if !t.started.load(AtOrd::SeqCst) { return false; }
    match &*lock_ok(&t.handle) { Some(h) => !h.is_finished(), None => false }
}

fn serp_thread_name(t: &SThread) -> SStr { sstring(lock_ok(&t.name).clone()) }

fn serp_thread_set_name(t: &SThread, name: &str) { *lock_ok(&t.name) = name.to_string(); }

fn serp_thread_ident(t: &SThread) -> i64 { t.ident.load(AtOrd::SeqCst) }

fn serp_thread_daemon(t: &SThread) -> bool { t.daemon }

fn serp_thread_cancel(t: &SThread) {
    *lock_ok(&t.cancel_m) = true;
    t.cancel_cv.notify_all();
}

fn serp_threads_join_all() {
    loop {
        let next = lock_ok(&TH_REGISTRY).pop();
        match next {
            None => break,
            Some(t) => {
                if t.ident.load(AtOrd::SeqCst) == th_ident() { continue; }
                let h = lock_ok(&t.handle).take();
                if let Some(h) = h { let _ = h.join(); }
            }
        }
    }
}

// ---------- asyncio task runtime (DECISIONS.md D45: baton-scheduled tasks) ----------
// Every task is an OS thread, but exactly one of them runs at any time: the runner
// holds the baton and hands it over when it suspends (await task / sleep / park /
// fd wait). Scheduling replays CPython's _run_once: a batch of the ready queue, then
// one readiness poll (I/O first, then expired timers), so dual runs interleave
// identically. Because there is never parallelism, Rc values are safe inside tasks.

struct AioTaskRec {
    go_m: Mutex<bool>,
    go_cv: Condvar,
}

struct AioTaskSt {
    rec: Arc<AioTaskRec>,
    done: bool,
    waiters: Vec<usize>,
}

struct AioFdWait {
    h: i64,
    write: bool,
    tid: usize,
    deadline: Option<std::time::Instant>,
}

struct AioLoop {
    tasks: std::collections::HashMap<usize, AioTaskSt>,
    ready: std::collections::VecDeque<usize>,
    timers: Vec<(std::time::Instant, u64, usize)>,
    fd_waits: Vec<AioFdWait>,
    fd_results: std::collections::HashMap<usize, bool>,
    current: usize,
    next_id: usize,
    seq: u64,
    batch_left: usize,
}

static AIO: std::sync::OnceLock<Mutex<AioLoop>> = std::sync::OnceLock::new();

thread_local! {
    static AIO_TID: std::cell::Cell<usize> = std::cell::Cell::new(usize::MAX);
}

fn aio_loop() -> &'static Mutex<AioLoop> {
    AIO.get_or_init(|| Mutex::new(AioLoop {
        tasks: std::collections::HashMap::new(),
        ready: std::collections::VecDeque::new(),
        timers: Vec::new(),
        fd_waits: Vec::new(),
        fd_results: std::collections::HashMap::new(),
        current: usize::MAX,
        next_id: 0,
        seq: 0,
        batch_left: 0,
    }))
}

fn aio_new_rec() -> Arc<AioTaskRec> {
    Arc::new(AioTaskRec { go_m: Mutex::new(false), go_cv: Condvar::new() })
}

fn aio_register(lp: &mut AioLoop) -> usize {
    let id = lp.next_id;
    lp.next_id += 1;
    lp.tasks.insert(id, AioTaskSt { rec: aio_new_rec(), done: false, waiters: Vec::new() });
    id
}

// The calling thread's task id; the first caller on a thread becomes a task in place
// (the main task of asyncio.run) and takes the baton if nobody holds it.
fn aio_me(lp: &mut AioLoop) -> usize {
    let cur = AIO_TID.with(|c| c.get());
    if cur != usize::MAX {
        return cur;
    }
    let id = aio_register(lp);
    AIO_TID.with(|c| c.set(id));
    if lp.current == usize::MAX {
        lp.current = id;
    }
    id
}

fn aio_now() -> std::time::Instant { std::time::Instant::now() }

fn aio_wait_go(rec: &AioTaskRec) {
    let mut g = lock_ok(&rec.go_m);
    while !*g {
        g = rec.go_cv.wait(g).unwrap_or_else(|e| e.into_inner());
    }
    *g = false;
}

fn aio_signal_go(rec: &AioTaskRec) {
    *lock_ok(&rec.go_m) = true;
    rec.go_cv.notify_one();
}

// One CPython `_run_once` readiness pass: poll the waited fds (timeout_ms < 0 = until
// the earliest deadline), queue I/O-ready tasks in registration order, then expired
// timers in (when, seq) order, then timed-out fd waits.
fn aio_select(lp: &mut AioLoop, block: bool) {
    let now = aio_now();
    let mut deadline: Option<std::time::Instant> = None;
    if block {
        for (t, _, _) in &lp.timers {
            deadline = Some(match deadline { Some(d) if d <= *t => d, _ => *t });
        }
        for w in &lp.fd_waits {
            if let Some(t) = w.deadline {
                deadline = Some(match deadline { Some(d) if d <= t => d, _ => t });
            }
        }
    }
    let timeout_ms: i64 = if !block {
        0
    } else {
        match deadline {
            Some(d) => if d > now { (d - now).as_millis() as i64 + 1 } else { 0 },
            None => -1,
        }
    };
    if !lp.fd_waits.is_empty() {
        let hs: Vec<i64> = lp.fd_waits.iter().map(|w| w.h).collect();
        let refs = sock_get_many(&hs);
        let mut instant: Vec<bool> = vec![false; hs.len()];
        let mut fds: Vec<SockPollFd> = Vec::new();
        let mut fd_idx: Vec<usize> = Vec::new();
        for (k, slot) in refs.iter().enumerate() {
            match slot {
                None => instant[k] = true,
                Some(arc) => {
                    let rec = sock_lock(arc);
                    let want_write = lp.fd_waits[k].write;
                    let buffered = !want_write
                        && matches!(&rec.kind, SockKind::Tls(c) if tls_buffered(c));
                    if buffered {
                        instant[k] = true;
                    } else if let Some(fd) = sock_raw(&rec) {
                        fds.push(SockPollFd {
                            fd,
                            events: if want_write { SOCK_POLL_OUT } else { SOCK_POLL_IN },
                            revents: 0,
                        });
                        fd_idx.push(k);
                    } else {
                        instant[k] = true;
                    }
                }
            }
        }
        let any_instant = instant.iter().any(|&f| f);
        if !fds.is_empty() {
            let wait = if any_instant { 0 } else if timeout_ms < 0 { 3_600_000 } else { timeout_ms };
            let n = sys_poll(&mut fds, wait);
            if n > 0 {
                for (pos, &k) in fd_idx.iter().enumerate() {
                    if fds[pos].revents != 0 {
                        instant[k] = true;
                    }
                }
            }
        }
        let mut keep: Vec<AioFdWait> = Vec::new();
        for (k, w) in lp.fd_waits.drain(..).enumerate() {
            if instant[k] {
                lp.fd_results.insert(w.tid, true);
                lp.ready.push_back(w.tid);
            } else {
                keep.push(w);
            }
        }
        lp.fd_waits = keep;
    } else if timeout_ms != 0 {
        match deadline {
            Some(d) => {
                let now2 = aio_now();
                if d > now2 {
                    std::thread::sleep(d - now2);
                }
            }
            None => {}
        }
    }
    let now = aio_now();
    lp.timers.sort_by(|a, b| (a.0, a.1).cmp(&(b.0, b.1)));
    let mut rest: Vec<(std::time::Instant, u64, usize)> = Vec::new();
    for (t, seq, tid) in lp.timers.drain(..) {
        if t <= now {
            lp.ready.push_back(tid);
        } else {
            rest.push((t, seq, tid));
        }
    }
    lp.timers = rest;
    let mut keep: Vec<AioFdWait> = Vec::new();
    for w in lp.fd_waits.drain(..) {
        match w.deadline {
            Some(d) if d <= now => {
                lp.fd_results.insert(w.tid, false);
                lp.ready.push_back(w.tid);
            }
            _ => keep.push(w),
        }
    }
    lp.fd_waits = keep;
}

// Hand the baton to the next runnable task; `me` has already been queued wherever it
// belongs (ready / timers / waiters / fd_waits) or is exiting. Returns once `me` is
// scheduled again (never, for an exiting task — the thread just ends).
fn aio_switch(mut lp: std::sync::MutexGuard<'static, AioLoop>, me: usize, exiting: bool) {
    loop {
        if lp.batch_left == 0 {
            aio_select(&mut lp, false);
            lp.batch_left = lp.ready.len();
        }
        if let Some(next) = lp.ready.pop_front() {
            lp.batch_left = lp.batch_left.saturating_sub(1);
            if next == me {
                return;
            }
            lp.current = next;
            let rec = lp.tasks.get(&next).map(|t| t.rec.clone());
            let mine = if exiting { None } else { lp.tasks.get(&me).map(|t| t.rec.clone()) };
            drop(lp);
            if let Some(r) = rec {
                aio_signal_go(&r);
            }
            if let Some(m) = mine {
                aio_wait_go(&m);
            }
            return;
        }
        if lp.timers.is_empty() && lp.fd_waits.is_empty() {
            // Nothing can ever become runnable: the loop is stuck (CPython hangs too).
            if exiting {
                return;
            }
            let mine = lp.tasks.get(&me).map(|t| t.rec.clone());
            drop(lp);
            if let Some(m) = mine {
                aio_wait_go(&m);
            }
            return;
        }
        aio_select(&mut lp, true);
        lp.batch_left = lp.ready.len();
    }
}

fn serp_aio_sleep(secs: f64) -> SRes<()> {
    let lp0 = aio_loop();
    let mut lp = lock_ok(lp0);
    let me = aio_me(&mut lp);
    if secs > 0.0 {
        let when = aio_now() + std::time::Duration::from_secs_f64(secs);
        lp.seq += 1;
        let seq = lp.seq;
        lp.timers.push((when, seq, me));
    } else {
        lp.ready.push_back(me);
    }
    aio_switch(lp, me, false);
    Ok(())
}

fn serp_aio_current() -> i64 {
    let mut lp = lock_ok(aio_loop());
    aio_me(&mut lp) as i64
}

// Suspend until another task calls wake(me); a wake that arrives first is not lost
// only if the waker runs after us — waiters must register before yielding, which
// the facades do (append id, then park).
fn serp_aio_park() -> SRes<()> {
    let mut lp = lock_ok(aio_loop());
    let me = aio_me(&mut lp);
    aio_switch(lp, me, false);
    Ok(())
}

fn serp_aio_wake(tid: i64) -> SRes<()> {
    let mut lp = lock_ok(aio_loop());
    let _ = aio_me(&mut lp);
    let t = tid as usize;
    if lp.tasks.contains_key(&t) && !lp.ready.contains(&t) {
        lp.ready.push_back(t);
    }
    Ok(())
}

// Suspend until socket handle `h` is readable (write=false) or writable; returns
// False on timeout (timeout_ms < 0 waits forever).
fn serp_aio_wait_fd(h: i64, write: i64, timeout_ms: i64) -> SRes<bool> {
    let mut lp = lock_ok(aio_loop());
    let me = aio_me(&mut lp);
    let deadline = if timeout_ms >= 0 {
        Some(aio_now() + std::time::Duration::from_millis(timeout_ms as u64))
    } else {
        None
    };
    lp.fd_waits.push(AioFdWait { h, write: write != 0, tid: me, deadline });
    aio_switch(lp, me, false);
    let mut lp = lock_ok(aio_loop());
    Ok(lp.fd_results.remove(&me).unwrap_or(false))
}

fn serp_aio_running() -> bool {
    AIO_TID.with(|c| c.get()) != usize::MAX
}

type AioBody = Box<dyn FnOnce() + Send>;

// Create a task: its first step is queued at the back of the ready queue (CPython
// call_soon); the body runs on a fresh thread once the baton reaches it.
fn aio_task_spawn(body: AioBody) -> usize {
    let mut lp = lock_ok(aio_loop());
    let _ = aio_me(&mut lp);
    let tid = aio_register(&mut lp);
    let rec = lp.tasks.get(&tid).map(|t| t.rec.clone()).expect("task rec");
    lp.ready.push_back(tid);
    drop(lp);
    serp_thread_spawn(move || {
        AIO_TID.with(|c| c.set(tid));
        aio_wait_go(&rec);
        body();
        let mut lp = lock_ok(aio_loop());
        let waiters: Vec<usize> = match lp.tasks.get_mut(&tid) {
            Some(t) => { t.done = true; std::mem::take(&mut t.waiters) }
            None => Vec::new(),
        };
        for w in waiters {
            if !lp.ready.contains(&w) {
                lp.ready.push_back(w);
            }
        }
        aio_switch(lp, tid, true);
    });
    tid
}

fn aio_task_done(tid: usize) -> bool {
    let lp = lock_ok(aio_loop());
    lp.tasks.get(&tid).map(|t| t.done).unwrap_or(true)
}

// Block the current task until `tid` finishes (no-op when it already has).
fn aio_task_wait(tid: usize) {
    loop {
        let mut lp = lock_ok(aio_loop());
        let me = aio_me(&mut lp);
        let done = lp.tasks.get(&tid).map(|t| t.done).unwrap_or(true);
        if done {
            return;
        }
        if let Some(t) = lp.tasks.get_mut(&tid) {
            t.waiters.push(me);
        }
        aio_switch(lp, me, false);
    }
}

pub struct STask<T> {
    tid: usize,
    slot: Arc<Mutex<Option<SRes<T>>>>,
}

fn serp_task_spawn<T, F>(f: F) -> STask<T>
where T: Send + 'static, F: FnOnce() -> SRes<T> + Send + 'static {
    let slot: Arc<Mutex<Option<SRes<T>>>> = Arc::new(Mutex::new(None));
    let s2 = slot.clone();
    let tid = aio_task_spawn(Box::new(move || {
        let r = f();
        *lock_ok(&s2) = Some(r);
    }));
    STask { tid, slot }
}

fn serp_task_await<T>(h: &STask<T>) -> SRes<T> {
    aio_task_wait(h.tid);
    match lock_ok(&h.slot).take() {
        Some(r) => r,
        None => Err(SerpErr::new("RuntimeError", "task result already taken".to_string())),
    }
}

fn serp_task_done<T>(h: &STask<T>) -> bool { aio_task_done(h.tid) }

// ----- asyncio sync primitives (handle tables; wake order mirrors CPython's
// futures-scheduled-via-call_soon so dual runs interleave identically) -----

struct AioEvent { set: bool, waiters: Vec<usize> }
struct AioLock { locked: bool, waiters: Vec<(usize, bool)> }
struct AioSem { value: i64, waiters: Vec<(usize, bool)> }
struct AioQueue {
    maxsize: i64,
    items: std::collections::VecDeque<SendVal>,
    getters: std::collections::VecDeque<usize>,
    putters: std::collections::VecDeque<usize>,
    unfinished: i64,
    join_waiters: Vec<usize>,
}

static AIO_EVENTS: Mutex<Vec<AioEvent>> = Mutex::new(Vec::new());
static AIO_LOCKS: Mutex<Vec<AioLock>> = Mutex::new(Vec::new());
static AIO_SEMS: Mutex<Vec<AioSem>> = Mutex::new(Vec::new());
static AIO_QUEUES: Mutex<Vec<AioQueue>> = Mutex::new(Vec::new());

fn aio_idx<T>(tbl: &[T], h: i64, what: &str) -> SRes<usize> {
    if h < 1 || h as usize > tbl.len() {
        return serp_err("ValueError", format!("invalid {} handle", what));
    }
    Ok(h as usize - 1)
}

// Queue `tid` at the back of the ready queue (CPython: fut.set_result -> call_soon).
fn aio_ready(tid: usize) {
    let mut lp = lock_ok(aio_loop());
    if lp.tasks.contains_key(&tid) && !lp.ready.contains(&tid) {
        lp.ready.push_back(tid);
    }
}

fn aio_me_now() -> usize {
    let mut lp = lock_ok(aio_loop());
    aio_me(&mut lp)
}

fn aio_park_now(me: usize) {
    let lp = lock_ok(aio_loop());
    aio_switch(lp, me, false);
}

fn serp_aio_ev_new() -> i64 {
    let mut t = lock_ok(&AIO_EVENTS);
    t.push(AioEvent { set: false, waiters: Vec::new() });
    t.len() as i64
}

fn serp_aio_ev_set(h: i64) -> SRes<()> {
    let waiters = {
        let mut t = lock_ok(&AIO_EVENTS);
        let i = aio_idx(&t, h, "event")?;
        if t[i].set { return Ok(()); }
        t[i].set = true;
        std::mem::take(&mut t[i].waiters)
    };
    for w in waiters { aio_ready(w); }
    Ok(())
}

fn serp_aio_ev_clear(h: i64) -> SRes<()> {
    let mut t = lock_ok(&AIO_EVENTS);
    let i = aio_idx(&t, h, "event")?;
    t[i].set = false;
    Ok(())
}

fn serp_aio_ev_is_set(h: i64) -> SRes<bool> {
    let t = lock_ok(&AIO_EVENTS);
    let i = aio_idx(&t, h, "event")?;
    Ok(t[i].set)
}

fn serp_aio_ev_wait(h: i64) -> SRes<bool> {
    let me = aio_me_now();
    loop {
        {
            let mut t = lock_ok(&AIO_EVENTS);
            let i = aio_idx(&t, h, "event")?;
            if t[i].set { return Ok(true); }
            t[i].waiters.push(me);
        }
        aio_park_now(me);
    }
}

fn serp_aio_lock_new() -> i64 {
    let mut t = lock_ok(&AIO_LOCKS);
    t.push(AioLock { locked: false, waiters: Vec::new() });
    t.len() as i64
}

// CPython Lock.acquire: fast path only when unlocked AND nobody is queued; a
// woken waiter stays queued until it runs, so newcomers cannot barge in.
fn serp_aio_lock_acquire(h: i64) -> SRes<bool> {
    let me = aio_me_now();
    {
        let mut t = lock_ok(&AIO_LOCKS);
        let i = aio_idx(&t, h, "lock")?;
        if !t[i].locked && t[i].waiters.is_empty() {
            t[i].locked = true;
            return Ok(true);
        }
        t[i].waiters.push((me, false));
    }
    loop {
        aio_park_now(me);
        let mut t = lock_ok(&AIO_LOCKS);
        let i = aio_idx(&t, h, "lock")?;
        let pos = t[i].waiters.iter().position(|(w, _)| *w == me);
        match pos {
            Some(p) if t[i].waiters[p].1 => {
                t[i].waiters.remove(p);
                t[i].locked = true;
                return Ok(true);
            }
            _ => continue,
        }
    }
}

fn serp_aio_lock_release(h: i64) -> SRes<()> {
    let next = {
        let mut t = lock_ok(&AIO_LOCKS);
        let i = aio_idx(&t, h, "lock")?;
        if !t[i].locked {
            return serp_err("RuntimeError", "Lock is not acquired.".into());
        }
        t[i].locked = false;
        match t[i].waiters.iter_mut().find(|(_, woken)| !*woken) {
            Some(w) => { w.1 = true; Some(w.0) }
            None => None,
        }
    };
    if let Some(w) = next { aio_ready(w); }
    Ok(())
}

fn serp_aio_lock_locked(h: i64) -> SRes<bool> {
    let t = lock_ok(&AIO_LOCKS);
    let i = aio_idx(&t, h, "lock")?;
    Ok(t[i].locked)
}

fn serp_aio_sem_new(value: i64) -> SRes<i64> {
    if value < 0 {
        return serp_err("ValueError", "Semaphore initial value must be >= 0".into());
    }
    let mut t = lock_ok(&AIO_SEMS);
    t.push(AioSem { value, waiters: Vec::new() });
    Ok(t.len() as i64)
}

fn aio_sem_wake_next(s: &mut AioSem) -> Option<usize> {
    match s.waiters.iter_mut().find(|(_, woken)| !*woken) {
        Some(w) => { w.1 = true; Some(w.0) }
        None => None,
    }
}

// CPython 3.11.1+ Semaphore: FIFO fairness (locked() is true while anyone waits);
// a woken waiter takes one unit and passes any surplus to the next waiter.
fn serp_aio_sem_acquire(h: i64) -> SRes<bool> {
    let me = aio_me_now();
    {
        let mut t = lock_ok(&AIO_SEMS);
        let i = aio_idx(&t, h, "semaphore")?;
        if t[i].value > 0 && t[i].waiters.is_empty() {
            t[i].value -= 1;
            return Ok(true);
        }
        t[i].waiters.push((me, false));
    }
    loop {
        aio_park_now(me);
        let next = {
            let mut t = lock_ok(&AIO_SEMS);
            let i = aio_idx(&t, h, "semaphore")?;
            let pos = t[i].waiters.iter().position(|(w, _)| *w == me);
            match pos {
                Some(p) if t[i].waiters[p].1 => {
                    t[i].waiters.remove(p);
                    t[i].value -= 1;
                    if t[i].value > 0 { aio_sem_wake_next(&mut t[i]) } else { None }
                }
                _ => continue,
            }
        };
        if let Some(w) = next { aio_ready(w); }
        return Ok(true);
    }
}

fn serp_aio_sem_release(h: i64, bounded: i64, initial: i64) -> SRes<()> {
    let next = {
        let mut t = lock_ok(&AIO_SEMS);
        let i = aio_idx(&t, h, "semaphore")?;
        if bounded != 0 && t[i].value >= initial {
            return serp_err("ValueError", "BoundedSemaphore released too many times".into());
        }
        t[i].value += 1;
        aio_sem_wake_next(&mut t[i])
    };
    if let Some(w) = next { aio_ready(w); }
    Ok(())
}

fn serp_aio_sem_locked(h: i64) -> SRes<bool> {
    let t = lock_ok(&AIO_SEMS);
    let i = aio_idx(&t, h, "semaphore")?;
    Ok(t[i].value == 0 || !t[i].waiters.is_empty())
}

fn serp_aio_sem_value(h: i64) -> SRes<i64> {
    let t = lock_ok(&AIO_SEMS);
    let i = aio_idx(&t, h, "semaphore")?;
    Ok(t[i].value)
}

fn serp_aio_q_new(maxsize: i64) -> i64 {
    let mut t = lock_ok(&AIO_QUEUES);
    t.push(AioQueue {
        maxsize,
        items: std::collections::VecDeque::new(),
        getters: std::collections::VecDeque::new(),
        putters: std::collections::VecDeque::new(),
        unfinished: 0,
        join_waiters: Vec::new(),
    });
    t.len() as i64
}

fn aio_q_full(q: &AioQueue) -> bool { q.maxsize > 0 && q.items.len() as i64 >= q.maxsize }

// asyncio.Queue.put: wait while full (re-checking after each wake), then put_nowait.
fn serp_aio_q_put(h: i64, item: &PVal, nowait: i64) -> SRes<bool> {
    let me = aio_me_now();
    loop {
        let wake = {
            let mut t = lock_ok(&AIO_QUEUES);
            let i = aio_idx(&t, h, "queue")?;
            if aio_q_full(&t[i]) {
                if nowait != 0 { return Ok(false); }
                t[i].putters.push_back(me);
                None
            } else {
                let sv = pv_to_send(item);
                t[i].items.push_back(sv);
                t[i].unfinished += 1;
                Some(t[i].getters.pop_front())
            }
        };
        match wake {
            None => aio_park_now(me),
            Some(g) => {
                if let Some(g) = g { aio_ready(g); }
                return Ok(true);
            }
        }
    }
}

fn serp_aio_q_get(h: i64, nowait: i64) -> SRes<bool> {
    let me = aio_me_now();
    loop {
        let got = {
            let mut t = lock_ok(&AIO_QUEUES);
            let i = aio_idx(&t, h, "queue")?;
            match t[i].items.pop_front() {
                None => {
                    if nowait != 0 { return Ok(false); }
                    t[i].getters.push_back(me);
                    None
                }
                Some(sv) => Some((sv, t[i].putters.pop_front())),
            }
        };
        match got {
            None => aio_park_now(me),
            Some((sv, p)) => {
                Q_LAST.with(|c| *c.borrow_mut() = Some(send_to_pv(sv)));
                if let Some(p) = p { aio_ready(p); }
                return Ok(true);
            }
        }
    }
}

fn serp_aio_q_qsize(h: i64) -> SRes<i64> {
    let t = lock_ok(&AIO_QUEUES);
    let i = aio_idx(&t, h, "queue")?;
    Ok(t[i].items.len() as i64)
}

fn serp_aio_q_maxsize(h: i64) -> SRes<i64> {
    let t = lock_ok(&AIO_QUEUES);
    let i = aio_idx(&t, h, "queue")?;
    Ok(t[i].maxsize)
}

fn serp_aio_q_task_done(h: i64) -> SRes<()> {
    let waiters = {
        let mut t = lock_ok(&AIO_QUEUES);
        let i = aio_idx(&t, h, "queue")?;
        if t[i].unfinished <= 0 {
            return serp_err("ValueError", "task_done() called too many times".into());
        }
        t[i].unfinished -= 1;
        if t[i].unfinished == 0 { std::mem::take(&mut t[i].join_waiters) } else { Vec::new() }
    };
    for w in waiters { aio_ready(w); }
    Ok(())
}

fn serp_aio_q_join(h: i64) -> SRes<()> {
    let me = aio_me_now();
    loop {
        {
            let mut t = lock_ok(&AIO_QUEUES);
            let i = aio_idx(&t, h, "queue")?;
            if t[i].unfinished == 0 { return Ok(()); }
            t[i].join_waiters.push(me);
        }
        aio_park_now(me);
    }
}

// ----- locks -----

struct LockSt { locked: bool, owner: i64, count: i64 }
struct LockRec { m: Mutex<LockSt>, cv: Condvar }
static LOCKS: Mutex<Vec<Arc<LockRec>>> = Mutex::new(Vec::new());

fn table_get<T>(tbl: &Mutex<Vec<Arc<T>>>, h: i64, what: &str) -> SRes<Arc<T>> {
    let v = lock_ok(tbl);
    if h < 1 || h as usize > v.len() {
        return serp_err("ValueError", format!("invalid {} handle", what));
    }
    Ok(v[h as usize - 1].clone())
}

fn table_push<T>(tbl: &Mutex<Vec<Arc<T>>>, rec: Arc<T>) -> i64 {
    let mut v = lock_ok(tbl);
    v.push(rec);
    v.len() as i64
}

fn serp_lock_new() -> i64 {
    table_push(&LOCKS, Arc::new(LockRec {
        m: Mutex::new(LockSt { locked: false, owner: 0, count: 0 }), cv: Condvar::new() }))
}

fn wait_deadline<'a, T>(cv: &Condvar, g: std::sync::MutexGuard<'a, T>,
                        deadline: Option<std::time::Instant>)
                        -> (std::sync::MutexGuard<'a, T>, bool) {
    match deadline {
        None => (cv.wait(g).unwrap_or_else(|e| e.into_inner()), false),
        Some(d) => {
            let now = std::time::Instant::now();
            if now >= d { return (g, true); }
            let (g, _) = cv.wait_timeout(g, d - now).unwrap_or_else(|e| e.into_inner());
            (g, false)
        }
    }
}

fn deadline_of(timeout_ms: i64) -> Option<std::time::Instant> {
    if timeout_ms < 0 { None }
    else { Some(std::time::Instant::now() + std::time::Duration::from_millis(timeout_ms as u64)) }
}

fn serp_lock_acquire(h: i64, timeout_ms: i64, reentrant_flag: i64) -> SRes<bool> {
    let reentrant = reentrant_flag != 0;
    let rec = table_get(&LOCKS, h, "lock")?;
    let me = th_ident();
    let mut st = lock_ok(&rec.m);
    if reentrant && st.locked && st.owner == me {
        st.count += 1;
        return Ok(true);
    }
    let deadline = deadline_of(timeout_ms);
    while st.locked {
        if timeout_ms == 0 { return Ok(false); }
        let (g, expired) = wait_deadline(&rec.cv, st, deadline);
        st = g;
        if expired && st.locked { return Ok(false); }
    }
    st.locked = true;
    st.owner = me;
    st.count = 1;
    Ok(true)
}

fn serp_lock_release(h: i64, reentrant_flag: i64) -> SRes<()> {
    let reentrant = reentrant_flag != 0;
    let rec = table_get(&LOCKS, h, "lock")?;
    let mut st = lock_ok(&rec.m);
    if !st.locked {
        return serp_err("RuntimeError", if reentrant {
            "cannot release un-acquired lock".into() } else { "release unlocked lock".into() });
    }
    if reentrant && st.owner != th_ident() {
        return serp_err("RuntimeError", "cannot release un-acquired lock".into());
    }
    st.count -= 1;
    if st.count <= 0 {
        st.locked = false;
        st.owner = 0;
        st.count = 0;
        drop(st);
        rec.cv.notify_one();
    }
    Ok(())
}

fn serp_lock_locked(h: i64) -> SRes<bool> {
    Ok(lock_ok(&table_get(&LOCKS, h, "lock")?.m).locked)
}

fn serp_lock_owned(h: i64) -> SRes<bool> {
    let rec = table_get(&LOCKS, h, "lock")?;
    let st = lock_ok(&rec.m);
    Ok(st.locked && st.owner == th_ident())
}

fn lock_release_save(rec: &LockRec) -> SRes<i64> {
    let mut st = lock_ok(&rec.m);
    if !st.locked || st.owner != th_ident() {
        return serp_err("RuntimeError", "cannot wait on un-acquired lock".into());
    }
    let saved = st.count;
    st.locked = false;
    st.owner = 0;
    st.count = 0;
    drop(st);
    rec.cv.notify_one();
    Ok(saved)
}

fn lock_acquire_restore(rec: &LockRec, count: i64) {
    let mut st = lock_ok(&rec.m);
    while st.locked {
        st = rec.cv.wait(st).unwrap_or_else(|e| e.into_inner());
    }
    st.locked = true;
    st.owner = th_ident();
    st.count = count.max(1);
}

// ----- events -----

struct EventRec { m: Mutex<bool>, cv: Condvar }
static EVENTS: Mutex<Vec<Arc<EventRec>>> = Mutex::new(Vec::new());

fn serp_event_new() -> i64 {
    table_push(&EVENTS, Arc::new(EventRec { m: Mutex::new(false), cv: Condvar::new() }))
}

fn serp_event_set(h: i64) -> SRes<()> {
    let rec = table_get(&EVENTS, h, "event")?;
    *lock_ok(&rec.m) = true;
    rec.cv.notify_all();
    Ok(())
}

fn serp_event_clear(h: i64) -> SRes<()> {
    *lock_ok(&table_get(&EVENTS, h, "event")?.m) = false;
    Ok(())
}

fn serp_event_is_set(h: i64) -> SRes<bool> {
    Ok(*lock_ok(&table_get(&EVENTS, h, "event")?.m))
}

fn serp_event_wait(h: i64, timeout_ms: i64) -> SRes<bool> {
    let rec = table_get(&EVENTS, h, "event")?;
    let deadline = deadline_of(timeout_ms);
    let mut st = lock_ok(&rec.m);
    while !*st {
        if timeout_ms == 0 { return Ok(false); }
        let (g, expired) = wait_deadline(&rec.cv, st, deadline);
        st = g;
        if expired && !*st { return Ok(false); }
    }
    Ok(true)
}

// ----- semaphores -----

struct SemRec { m: Mutex<i64>, cv: Condvar }
static SEMS: Mutex<Vec<Arc<SemRec>>> = Mutex::new(Vec::new());

fn serp_sem_new(value: i64) -> SRes<i64> {
    if value < 0 {
        return serp_err("ValueError", "semaphore initial value must be >= 0".into());
    }
    Ok(table_push(&SEMS, Arc::new(SemRec { m: Mutex::new(value), cv: Condvar::new() })))
}

fn serp_sem_acquire(h: i64, timeout_ms: i64) -> SRes<bool> {
    let rec = table_get(&SEMS, h, "semaphore")?;
    let deadline = deadline_of(timeout_ms);
    let mut st = lock_ok(&rec.m);
    while *st <= 0 {
        if timeout_ms == 0 { return Ok(false); }
        let (g, expired) = wait_deadline(&rec.cv, st, deadline);
        st = g;
        if expired && *st <= 0 { return Ok(false); }
    }
    *st -= 1;
    Ok(true)
}

fn serp_sem_release(h: i64, n: i64) -> SRes<()> {
    if n < 1 {
        return serp_err("ValueError", "n must be one or more".into());
    }
    let rec = table_get(&SEMS, h, "semaphore")?;
    *lock_ok(&rec.m) += n;
    rec.cv.notify_all();
    Ok(())
}

fn serp_sem_value(h: i64) -> SRes<i64> {
    Ok(*lock_ok(&table_get(&SEMS, h, "semaphore")?.m))
}

// ----- conditions -----

struct CondSt { waiting: i64, tickets: i64 }
struct CondRec { m: Mutex<CondSt>, cv: Condvar }
static CONDS: Mutex<Vec<Arc<CondRec>>> = Mutex::new(Vec::new());

fn serp_cond_new() -> i64 {
    table_push(&CONDS, Arc::new(CondRec {
        m: Mutex::new(CondSt { waiting: 0, tickets: 0 }), cv: Condvar::new() }))
}

fn serp_cond_wait(h: i64, lock_h: i64, timeout_ms: i64) -> SRes<bool> {
    let cond = table_get(&CONDS, h, "condition")?;
    let lock = table_get(&LOCKS, lock_h, "lock")?;
    let saved = lock_release_save(&lock)?;
    let deadline = deadline_of(timeout_ms);
    let got;
    {
        let mut st = lock_ok(&cond.m);
        st.waiting += 1;
        loop {
            if st.tickets > 0 {
                st.tickets -= 1;
                st.waiting -= 1;
                got = true;
                break;
            }
            if timeout_ms == 0 {
                st.waiting -= 1;
                got = false;
                break;
            }
            let (g, expired) = wait_deadline(&cond.cv, st, deadline);
            st = g;
            if expired && st.tickets <= 0 {
                st.waiting -= 1;
                got = false;
                break;
            }
        }
    }
    lock_acquire_restore(&lock, saved);
    Ok(got)
}

fn serp_cond_notify(h: i64, n: i64) -> SRes<()> {
    let cond = table_get(&CONDS, h, "condition")?;
    let mut st = lock_ok(&cond.m);
    let avail = (st.waiting - st.tickets).max(0);
    st.tickets += n.min(avail);
    drop(st);
    cond.cv.notify_all();
    Ok(())
}

// ----- barriers -----

struct BarSt { count: i64, generation: i64, broken: bool }
struct BarRec { parties: i64, m: Mutex<BarSt>, cv: Condvar }
static BARS: Mutex<Vec<Arc<BarRec>>> = Mutex::new(Vec::new());

fn serp_barrier_new(parties: i64) -> SRes<i64> {
    if parties < 1 {
        return serp_err("ValueError", "parties must be > 0".into());
    }
    Ok(table_push(&BARS, Arc::new(BarRec { parties,
        m: Mutex::new(BarSt { count: 0, generation: 0, broken: false }), cv: Condvar::new() })))
}

// Returns the arrival index, -1 when the barrier is broken, -2 on timeout (breaks it).
fn serp_barrier_wait(h: i64, timeout_ms: i64) -> SRes<i64> {
    let rec = table_get(&BARS, h, "barrier")?;
    let deadline = deadline_of(timeout_ms);
    let mut st = lock_ok(&rec.m);
    if st.broken { return Ok(-1); }
    let idx = st.count;
    st.count += 1;
    if st.count == rec.parties {
        st.count = 0;
        st.generation += 1;
        drop(st);
        rec.cv.notify_all();
        return Ok(idx);
    }
    let gen = st.generation;
    while st.generation == gen && !st.broken {
        let (g, expired) = wait_deadline(&rec.cv, st, deadline);
        st = g;
        if expired && st.generation == gen && !st.broken {
            st.broken = true;
            drop(st);
            rec.cv.notify_all();
            return Ok(-2);
        }
    }
    if st.broken && st.generation == gen { return Ok(-1); }
    Ok(idx)
}

fn serp_barrier_reset(h: i64) -> SRes<()> {
    let rec = table_get(&BARS, h, "barrier")?;
    let mut st = lock_ok(&rec.m);
    if st.count > 0 {
        st.broken = true;
        st.generation += 1;
    } else {
        st.broken = false;
    }
    st.count = 0;
    drop(st);
    rec.cv.notify_all();
    Ok(())
}

fn serp_barrier_abort(h: i64) -> SRes<()> {
    let rec = table_get(&BARS, h, "barrier")?;
    lock_ok(&rec.m).broken = true;
    rec.cv.notify_all();
    Ok(())
}

fn serp_barrier_parties(h: i64) -> SRes<i64> { Ok(table_get(&BARS, h, "barrier")?.parties) }

fn serp_barrier_n_waiting(h: i64) -> SRes<i64> {
    Ok(lock_ok(&table_get(&BARS, h, "barrier")?.m).count)
}

fn serp_barrier_broken(h: i64) -> SRes<bool> {
    Ok(lock_ok(&table_get(&BARS, h, "barrier")?.m).broken)
}

// ----- queues (PyVal items deep-copied across threads) -----

enum SendVal {
    None_, Bool(bool), Int(i64), Float(f64), Str(String), Bytes(Vec<u8>),
    List(Vec<SendVal>), Dict(Vec<(SendVal, SendVal)>),
}

fn pv_to_send(v: &PVal) -> SendVal {
    match &*v.0 {
        PValRepr::None_ => SendVal::None_,
        PValRepr::Bool(b) => SendVal::Bool(*b),
        PValRepr::Int(i) => SendVal::Int(*i),
        PValRepr::Float(f) => SendVal::Float(*f),
        PValRepr::Str(s) => SendVal::Str(s.as_str().to_string()),
        PValRepr::Bytes(b) => SendVal::Bytes((*b.v).clone()),
        PValRepr::List(l) => SendVal::List(l.iter().map(pv_to_send).collect()),
        PValRepr::Dict(d) => SendVal::Dict(
            d.items_it().map(|(k, val)| (pv_to_send(k), pv_to_send(val))).collect()),
    }
}

fn send_to_pv(v: SendVal) -> PVal {
    match v {
        SendVal::None_ => pyval_none(),
        SendVal::Bool(b) => pyval_bool(b),
        SendVal::Int(i) => pyval_int(i),
        SendVal::Float(f) => pyval_float(f),
        SendVal::Str(s) => pyval_str(sstring(s)),
        SendVal::Bytes(b) => pyval_bytes(sbytes(b)),
        SendVal::List(l) => pyval_list(l.into_iter().map(send_to_pv).collect()),
        SendVal::Dict(d) => {
            let mut out: SerpDict<PVal, PVal> = SerpDict::new();
            for (k, val) in d { out.set(send_to_pv(k), send_to_pv(val)); }
            pyval_dict(out)
        }
    }
}

struct QSt { items: std::collections::VecDeque<SendVal>, unfinished: i64 }
struct QueueRec { maxsize: i64, lifo: bool, m: Mutex<QSt>, not_empty: Condvar,
                  not_full: Condvar, all_done: Condvar }
static QUEUES: Mutex<Vec<Arc<QueueRec>>> = Mutex::new(Vec::new());

fn serp_q_new(maxsize: i64, lifo_flag: i64) -> i64 {
    let lifo = lifo_flag != 0;
    table_push(&QUEUES, Arc::new(QueueRec { maxsize, lifo,
        m: Mutex::new(QSt { items: std::collections::VecDeque::new(), unfinished: 0 }),
        not_empty: Condvar::new(), not_full: Condvar::new(), all_done: Condvar::new() }))
}

fn serp_q_put(h: i64, item: &PVal, block_flag: i64, timeout_ms: i64) -> SRes<bool> {
    let block = block_flag != 0;
    let q = table_get(&QUEUES, h, "queue")?;
    let deadline = deadline_of(timeout_ms);
    let mut st = lock_ok(&q.m);
    if q.maxsize > 0 {
        while st.items.len() as i64 >= q.maxsize {
            if !block || timeout_ms == 0 { return Ok(false); }
            let (g, expired) = wait_deadline(&q.not_full, st, deadline);
            st = g;
            if expired && st.items.len() as i64 >= q.maxsize { return Ok(false); }
        }
    }
    st.items.push_back(pv_to_send(item));
    st.unfinished += 1;
    drop(st);
    q.not_empty.notify_one();
    Ok(true)
}

fn serp_q_get(h: i64, block_flag: i64, timeout_ms: i64) -> SRes<bool> {
    let block = block_flag != 0;
    let q = table_get(&QUEUES, h, "queue")?;
    let deadline = deadline_of(timeout_ms);
    let mut st = lock_ok(&q.m);
    while st.items.is_empty() {
        if !block || timeout_ms == 0 { return Ok(false); }
        let (g, expired) = wait_deadline(&q.not_empty, st, deadline);
        st = g;
        if expired && st.items.is_empty() { return Ok(false); }
    }
    let item = if q.lifo { st.items.pop_back() } else { st.items.pop_front() };
    drop(st);
    q.not_full.notify_one();
    Q_LAST.with(|c| *c.borrow_mut() = item.map(send_to_pv));
    Ok(true)
}

fn serp_q_last() -> PVal {
    Q_LAST.with(|c| c.borrow_mut().take().unwrap_or_else(pyval_none))
}

fn serp_q_qsize(h: i64) -> SRes<i64> {
    Ok(lock_ok(&table_get(&QUEUES, h, "queue")?.m).items.len() as i64)
}

fn serp_q_task_done(h: i64) -> SRes<()> {
    let q = table_get(&QUEUES, h, "queue")?;
    let mut st = lock_ok(&q.m);
    if st.unfinished <= 0 {
        return serp_err("ValueError", "task_done() called too many times".into());
    }
    st.unfinished -= 1;
    if st.unfinished == 0 {
        drop(st);
        q.all_done.notify_all();
    }
    Ok(())
}

fn serp_q_join(h: i64) -> SRes<()> {
    let q = table_get(&QUEUES, h, "queue")?;
    let mut st = lock_ok(&q.m);
    while st.unfinished > 0 {
        st = q.all_done.wait(st).unwrap_or_else(|e| e.into_inner());
    }
    Ok(())
}
