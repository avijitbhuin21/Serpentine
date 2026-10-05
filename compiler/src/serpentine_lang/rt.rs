// Serpentine LLVM-backend runtime ABI (Phase 5). This file is CONCATENATED after
// prelude.rs and compiled ONCE per (prelude+rt, rustc, target) into a cached rlib
// that Backend-B objects link against. Every symbol here is `extern "C"`.
//
// ABI contract (mirrored by llvmgen.py):
//   SStr    = opaque 24-byte blob, align 8  ([3 x i64] on the LLVM side)
//   RtList  = { data: *mut u8, len: i64, cap: i64 }   (element size supplied per call)
//   SErrC   = { kind: SStr, msg: SStr }
//   status  = i8 (0 ok, 1 error pending â€” pick the error up with rt_err_take)
// Ownership: values cross the boundary as raw blobs; the CALLER owns everything
// it passes by pointer unless a function is documented as consuming it. All
// type-directed clone/drop logic lives in generated LLVM code.

use std::alloc::{alloc as rust_alloc, dealloc as rust_dealloc, Layout};

const _SSTR_SIZE_OK: () = assert!(std::mem::size_of::<SStr>() == 24);
const _SSTR_ALIGN_OK: () = assert!(std::mem::align_of::<SStr>() == 8);

#[repr(C)]
pub struct RtList {
    pub data: *mut u8,
    pub len: i64,
    pub cap: i64,
}

#[repr(C)]
pub struct SErrC {
    pub kind: SStr,
    pub msg: SStr,
}

std::thread_local! {
    static PENDING: std::cell::RefCell<Option<SerpErr>> = std::cell::RefCell::new(None);
}

fn set_pending(e: SerpErr) {
    PENDING.with(|p| *p.borrow_mut() = Some(e));
}

fn take_pending() -> SerpErr {
    PENDING.with(|p| p.borrow_mut().take()).expect("serp rt: no pending error")
}

unsafe fn s(p: *const SStr) -> &'static str {
    (*p).as_str()
}

unsafe fn bytes<'a>(p: *const u8, len: i64) -> &'a str {
    std::str::from_utf8_unchecked(std::slice::from_raw_parts(p, len as usize))
}

// ---------- errors ----------

#[no_mangle]
pub unsafe extern "C" fn rt_raise(kind: *const SStr, msg: *const SStr) {
    set_pending(SerpErr::new(s(kind), s(msg).to_string()));
}

#[no_mangle]
pub unsafe extern "C" fn rt_raise_static(kp: *const u8, kl: i64, mp: *const u8, ml: i64) {
    set_pending(SerpErr::new(bytes(kp, kl), bytes(mp, ml).to_string()));
}

#[no_mangle]
pub unsafe extern "C" fn rt_err_take(out: *mut SErrC) {
    let e = take_pending();
    serp_tb_clear();
    out.write(SErrC { kind: sstr(&e.kind), msg: sstr(&e.msg) });
}

#[no_mangle]
pub unsafe extern "C" fn rt_tb_push(fp: *const u8, fl: i64, line: i64, np: *const u8, nl: i64) {
    serp_tb_push(bytes(fp, fl), line, bytes(np, nl));
}

#[no_mangle]
pub unsafe extern "C" fn rt_main_trampoline(entry: *const u8) -> i32 {
    #[cfg(unix)]
    {
        extern "C" {
            fn signal(sig: i32, handler: usize) -> usize;
        }
        signal(13, 1);
    }
    let f = entry as usize;
    let t = std::thread::Builder::new().name("main".into()).stack_size(SERP_STACK)
        .spawn(move || {
            let e: extern "C" fn() = std::mem::transmute(f);
            e();
        })
        .expect("spawn main thread");
    if t.join().is_err() {
        return 101;
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn rt_err_reraise(e: *const SErrC) {
    set_pending(SerpErr::new((*e).kind.as_str(), (*e).msg.as_str().to_string()));
}

#[no_mangle]
pub unsafe extern "C" fn rt_err_matches(e: *const SErrC, cp: *const u8, cl: i64) -> i8 {
    let err = SerpErr::new((*e).kind.as_str(), String::new());
    err.matches(bytes(cp, cl)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_err_msg(e: *const SErrC, out: *mut SStr) {
    out.write(sstr((*e).msg.as_str()));
}

#[no_mangle]
pub unsafe extern "C" fn rt_err_repr(e: *const SErrC, out: *mut SStr) {
    out.write(sstring(format!("{}({})", (*e).kind.as_str(), (*e).msg.as_str().py_repr())));
}

#[no_mangle]
pub unsafe extern "C" fn rt_abort_pending() -> ! {
    let e = take_pending();
    serp_abort(e)
}

// ---------- strings ----------

#[no_mangle]
pub unsafe extern "C" fn rt_str_new(p: *const u8, len: i64, out: *mut SStr) {
    out.write(sstr(bytes(p, len)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_clone(src: *const SStr, dst: *mut SStr) {
    dst.write((*src).clone());
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_drop(p: *mut SStr) {
    std::ptr::drop_in_place(p);
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_concat(a: *const SStr, b: *const SStr, out: *mut SStr) {
    out.write(sstring(format!("{}{}", s(a), s(b))));
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_repeat(a: *const SStr, n: i64, out: *mut SStr) {
    let n = if n < 0 { 0 } else { n as usize };
    out.write(sstring(s(a).repeat(n)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_eq(a: *const SStr, b: *const SStr) -> i8 {
    (s(a) == s(b)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_cmp(a: *const SStr, b: *const SStr) -> i32 {
    match s(a).cmp(s(b)) {
        std::cmp::Ordering::Less => -1,
        std::cmp::Ordering::Equal => 0,
        std::cmp::Ordering::Greater => 1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_len(p: *const SStr) -> i64 {
    py_len_str(s(p))
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_is_empty(p: *const SStr) -> i8 {
    s(p).is_empty() as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_contains(h: *const SStr, n: *const SStr) -> i8 {
    s(h).contains(s(n)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_startswith(h: *const SStr, n: *const SStr) -> i8 {
    s(h).starts_with(s(n)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_endswith(h: *const SStr, n: *const SStr) -> i8 {
    s(h).ends_with(s(n)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_find(h: *const SStr, n: *const SStr) -> i64 {
    py_find(s(h), s(n))
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_replace(a: *const SStr, from: *const SStr, to: *const SStr,
                                        out: *mut SStr) {
    out.write(py_replace(s(a), s(from), s(to)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_strip(a: *const SStr, out: *mut SStr) { out.write(py_strip(s(a))); }
#[no_mangle]
pub unsafe extern "C" fn rt_str_lstrip(a: *const SStr, out: *mut SStr) { out.write(py_lstrip(s(a))); }
#[no_mangle]
pub unsafe extern "C" fn rt_str_rstrip(a: *const SStr, out: *mut SStr) { out.write(py_rstrip(s(a))); }
#[no_mangle]
pub unsafe extern "C" fn rt_str_upper(a: *const SStr, out: *mut SStr) { out.write(py_upper(s(a))); }
#[no_mangle]
pub unsafe extern "C" fn rt_str_lower(a: *const SStr, out: *mut SStr) { out.write(py_lower(s(a))); }

unsafe fn vec_sstr_to_rtlist(v: Vec<SStr>, out: *mut RtList) {
    let mut v = std::mem::ManuallyDrop::new(v);
    out.write(RtList {
        data: v.as_mut_ptr() as *mut u8,
        len: v.len() as i64,
        cap: v.capacity() as i64,
    });
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_split(a: *const SStr, sep: *const SStr, out: *mut RtList) -> i8 {
    match py_split(s(a), s(sep)) {
        Ok(v) => { vec_sstr_to_rtlist(v, out); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_split_ws(a: *const SStr, out: *mut RtList) {
    vec_sstr_to_rtlist(py_split_ws(s(a)), out);
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_chars(a: *const SStr, out: *mut RtList) {
    vec_sstr_to_rtlist(py_chars(s(a)).collect(), out);
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_join(sep: *const SStr, list: *const RtList, out: *mut SStr) {
    let l = &*list;
    let items = std::slice::from_raw_parts(l.data as *const SStr, l.len as usize);
    let parts: Vec<&str> = items.iter().map(|x| x.as_str()).collect();
    out.write(sstring(parts.join(s(sep))));
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_index(a: *const SStr, i: i64, out: *mut SStr) -> i8 {
    match py_str_idx(s(a), i) {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_slice(a: *const SStr, lo: i64, has_lo: i8, hi: i64, has_hi: i8,
                                      out: *mut SStr) {
    let lo = if has_lo != 0 { Some(lo) } else { None };
    let hi = if has_hi != 0 { Some(hi) } else { None };
    out.write(py_str_slice(s(a), lo, hi));
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_ord(a: *const SStr, out: *mut i64) -> i8 {
    match py_ord(s(a)) {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_chr(i: i64, out: *mut SStr) -> i8 {
    match py_chr(i) {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_parse_i64(a: *const SStr, out: *mut i64) -> i8 {
    match py_int_from_str(s(a)) {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_parse_f64(a: *const SStr, out: *mut f64) -> i8 {
    match py_float_from_str(s(a)) {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

// ---------- string builder (f-strings, repr, print) ----------

#[no_mangle]
pub unsafe extern "C" fn rt_sb_new() -> *mut String {
    Box::into_raw(Box::new(String::new()))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sb_push_bytes(sb: *mut String, p: *const u8, len: i64) {
    (*sb).push_str(bytes(p, len));
}

#[no_mangle]
pub unsafe extern "C" fn rt_sb_push_str(sb: *mut String, a: *const SStr) {
    (*sb).push_str(s(a));
}

#[no_mangle]
pub unsafe extern "C" fn rt_sb_push_repr_str(sb: *mut String, a: *const SStr) {
    (*sb).push_str(&s(a).py_repr());
}

#[no_mangle]
pub unsafe extern "C" fn rt_sb_push_i64(sb: *mut String, v: i64) {
    (*sb).push_str(&v.to_string());
}

#[no_mangle]
pub unsafe extern "C" fn rt_sb_push_f64(sb: *mut String, v: f64) {
    (*sb).push_str(&py_float_repr(v));
}

#[no_mangle]
pub unsafe extern "C" fn rt_sb_push_f64_prec(sb: *mut String, v: f64, prec: i64) {
    (*sb).push_str(&format!("{:.*}", prec as usize, v));
}

#[no_mangle]
pub unsafe extern "C" fn rt_sb_push_padded(sb: *mut String, a: *const SStr, align: u8, width: i64) {
    let text = s(a);
    let w = width as usize;
    let out = match align {
        b'<' => format!("{:<w$}", text, w = w),
        b'^' => format!("{:^w$}", text, w = w),
        _ => format!("{:>w$}", text, w = w),
    };
    (*sb).push_str(&out);
}

#[no_mangle]
pub unsafe extern "C" fn rt_sb_finish(sb: *mut String, out: *mut SStr) {
    let boxed = Box::from_raw(sb);
    out.write(sstring(*boxed));
}

// ---------- lists (raw buffers; element moves/drops happen in generated code) ----------

unsafe fn list_layout(cap: i64, elem_size: i64) -> Layout {
    Layout::from_size_align_unchecked((cap * elem_size) as usize, 8)
}

#[no_mangle]
pub unsafe extern "C" fn rt_list_grow(l: *mut RtList, elem_size: i64, min_cap: i64) {
    let list = &mut *l;
    let mut new_cap = if list.cap == 0 { 4 } else { list.cap * 2 };
    if new_cap < min_cap { new_cap = min_cap; }
    let new_ptr = rust_alloc(list_layout(new_cap, elem_size));
    if list.cap > 0 {
        std::ptr::copy_nonoverlapping(list.data, new_ptr, (list.len * elem_size) as usize);
        rust_dealloc(list.data, list_layout(list.cap, elem_size));
    }
    list.data = new_ptr;
    list.cap = new_cap;
}

#[no_mangle]
pub unsafe extern "C" fn rt_list_free(l: *mut RtList, elem_size: i64) {
    let list = &mut *l;
    if list.cap > 0 {
        rust_dealloc(list.data, list_layout(list.cap, elem_size));
    }
    list.data = std::ptr::null_mut();
    list.len = 0;
    list.cap = 0;
}

#[no_mangle]
pub unsafe extern "C" fn rt_list_remove(l: *mut RtList, elem_size: i64, idx: i64) {
    let list = &mut *l;
    let p = list.data.offset((idx * elem_size) as isize);
    std::ptr::copy(p.offset(elem_size as isize), p,
                   ((list.len - idx - 1) * elem_size) as usize);
    list.len -= 1;
}

#[no_mangle]
pub unsafe extern "C" fn rt_list_insert(l: *mut RtList, elem_size: i64, idx: i64, src: *const u8) {
    let list = &mut *l;
    if list.len == list.cap {
        rt_list_grow(l, elem_size, list.len + 1);
    }
    let list = &mut *l;
    let p = list.data.offset((idx * elem_size) as isize);
    std::ptr::copy(p, p.offset(elem_size as isize), ((list.len - idx) * elem_size) as usize);
    std::ptr::copy_nonoverlapping(src, p, elem_size as usize);
    list.len += 1;
}

#[no_mangle]
pub unsafe extern "C" fn rt_list_reverse(l: *mut RtList, elem_size: i64) {
    let list = &mut *l;
    let mut i: i64 = 0;
    let mut j = list.len - 1;
    let es = elem_size as usize;
    let mut tmp = vec![0u8; es];
    while i < j {
        let a = list.data.offset((i * elem_size) as isize);
        let b = list.data.offset((j * elem_size) as isize);
        std::ptr::copy_nonoverlapping(a, tmp.as_mut_ptr(), es);
        std::ptr::copy_nonoverlapping(b, a, es);
        std::ptr::copy_nonoverlapping(tmp.as_ptr(), b, es);
        i += 1;
        j -= 1;
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_list_sort(l: *mut RtList, elem_size: i64,
                                      cmp: unsafe extern "C" fn(*const u8, *const u8) -> i32) {
    let list = &mut *l;
    let n = list.len as usize;
    if n < 2 { return; }
    let es = elem_size as usize;
    // Stable insertion-position sort over an index permutation, then apply it.
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&a, &b| {
        let pa = list.data.add(a * es) as *const u8;
        let pb = list.data.add(b * es) as *const u8;
        cmp(pa, pb).cmp(&0)
    });
    let mut scratch = vec![0u8; n * es];
    for (dst, &srci) in order.iter().enumerate() {
        std::ptr::copy_nonoverlapping(list.data.add(srci * es),
                                      scratch.as_mut_ptr().add(dst * es), es);
    }
    std::ptr::copy_nonoverlapping(scratch.as_ptr(), list.data, n * es);
}

// ---------- Shared[T] refcount boxes: { strong, weak, borrow } header + payload ----------

#[no_mangle]
pub unsafe extern "C" fn rt_shared_alloc(payload_size: i64) -> *mut u8 {
    let layout = Layout::from_size_align_unchecked((24 + payload_size) as usize, 8);
    let p = rust_alloc(layout);
    (p as *mut i64).write(1);            // strong
    (p as *mut i64).offset(1).write(1);  // weak (collective strong hold)
    (p as *mut i64).offset(2).write(0);  // borrow state (0 free, >0 shared, -1 mut)
    p
}

#[no_mangle]
pub unsafe extern "C" fn rt_shared_free(p: *mut u8, payload_size: i64) {
    let layout = Layout::from_size_align_unchecked((24 + payload_size) as usize, 8);
    rust_dealloc(p, layout);
}

// ---------- files ----------

#[no_mangle]
pub unsafe extern "C" fn rt_file_open(path: *const SStr, mode: *const SStr,
                                      out: *mut *mut SerpFile) -> i8 {
    match serp_open(s(path), s(mode)) {
        Ok(f) => { out.write(Box::into_raw(Box::new(f))); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_file_read(f: *mut SerpFile, out: *mut SStr) -> i8 {
    match (*f).read_all() {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_file_write(f: *mut SerpFile, a: *const SStr, out: *mut i64) -> i8 {
    match (*f).write_str(s(a)) {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_file_close(f: *mut SerpFile) {
    (*f).close();
}

#[no_mangle]
pub unsafe extern "C" fn rt_file_drop(f: *mut SerpFile) {
    drop(Box::from_raw(f));
}

// ---------- io / sys / misc ----------

#[no_mangle]
pub unsafe extern "C" fn rt_print(a: *const SStr) {
    println!("{}", s(a));
}

#[no_mangle]
pub unsafe extern "C" fn rt_print_empty() {
    println!();
}

#[no_mangle]
pub unsafe extern "C" fn rt_input(out: *mut SStr) -> i8 {
    match serp_input() {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_argv(out: *mut RtList) {
    vec_sstr_to_rtlist(serp_argv(), out);
}

#[no_mangle]
pub unsafe extern "C" fn rt_exit(code: i64) -> ! {
    process::exit(code as i32);
}

#[no_mangle]
pub unsafe extern "C" fn rt_round0(v: f64, out: *mut i64) -> i8 {
    match py_round0(v) {
        Ok(r) => { out.write(r); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_round_n(v: f64, n: i64) -> f64 {
    py_round_n(v, n)
}

#[no_mangle]
pub unsafe extern "C" fn rt_int_from_f64(v: f64, out: *mut i64) -> i8 {
    match py_int_from_f(v) {
        Ok(r) => { out.write(r); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_f64_floormod(a: f64, b: f64, is_mod: i8, out: *mut f64) -> i8 {
    let r = if is_mod != 0 { serp_mod_f(a, b) } else { serp_floordiv_f(a, b) };
    match r {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

// ---------- rtlib: serp_math / serp_random / serp_time ----------

unsafe fn st_f(r: SRes<f64>, out: *mut f64) -> i8 {
    match r { Ok(v) => { out.write(v); 0 } Err(e) => { set_pending(e); 1 } }
}

unsafe fn st_i(r: SRes<i64>, out: *mut i64) -> i8 {
    match r { Ok(v) => { out.write(v); 0 } Err(e) => { set_pending(e); 1 } }
}

#[no_mangle]
pub unsafe extern "C" fn rt_math_sqrt(x: f64, out: *mut f64) -> i8 { st_f(serp_math_sqrt(x), out) }

#[no_mangle]
pub extern "C" fn rt_math_sin(x: f64) -> f64 { serp_math_sin(x) }

#[no_mangle]
pub extern "C" fn rt_math_cos(x: f64) -> f64 { serp_math_cos(x) }

#[no_mangle]
pub extern "C" fn rt_math_tan(x: f64) -> f64 { serp_math_tan(x) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_log(x: f64, out: *mut f64) -> i8 { st_f(serp_math_log(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_exp(x: f64, out: *mut f64) -> i8 { st_f(serp_math_exp(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_pow(x: f64, y: f64, out: *mut f64) -> i8 { st_f(serp_math_pow(x, y), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_floor(x: f64, out: *mut i64) -> i8 { st_i(serp_math_floor(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_ceil(x: f64, out: *mut i64) -> i8 { st_i(serp_math_ceil(x), out) }

#[no_mangle]
pub extern "C" fn rt_math_isnan(x: f64) -> i8 { serp_math_isnan(x) as i8 }

#[no_mangle]
pub extern "C" fn rt_math_isinf(x: f64) -> i8 { serp_math_isinf(x) as i8 }

#[no_mangle]
pub extern "C" fn rt_math_isfinite(x: f64) -> i8 { serp_math_isfinite(x) as i8 }

#[no_mangle]
pub unsafe extern "C" fn rt_math_acos(x: f64, out: *mut f64) -> i8 { st_f(serp_math_acos(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_asin(x: f64, out: *mut f64) -> i8 { st_f(serp_math_asin(x), out) }

#[no_mangle]
pub extern "C" fn rt_math_atan(x: f64) -> f64 { serp_math_atan(x) }

#[no_mangle]
pub extern "C" fn rt_math_atan2(y: f64, x: f64) -> f64 { serp_math_atan2(y, x) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_acosh(x: f64, out: *mut f64) -> i8 { st_f(serp_math_acosh(x), out) }

#[no_mangle]
pub extern "C" fn rt_math_asinh(x: f64) -> f64 { serp_math_asinh(x) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_atanh(x: f64, out: *mut f64) -> i8 { st_f(serp_math_atanh(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_cosh(x: f64, out: *mut f64) -> i8 { st_f(serp_math_cosh(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_sinh(x: f64, out: *mut f64) -> i8 { st_f(serp_math_sinh(x), out) }

#[no_mangle]
pub extern "C" fn rt_math_tanh(x: f64) -> f64 { serp_math_tanh(x) }

#[no_mangle]
pub extern "C" fn rt_math_cbrt(x: f64) -> f64 { serp_math_cbrt(x) }

#[no_mangle]
pub extern "C" fn rt_math_degrees(x: f64) -> f64 { serp_math_degrees(x) }

#[no_mangle]
pub extern "C" fn rt_math_radians(x: f64) -> f64 { serp_math_radians(x) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_exp2(x: f64, out: *mut f64) -> i8 { st_f(serp_math_exp2(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_expm1(x: f64, out: *mut f64) -> i8 { st_f(serp_math_expm1(x), out) }

#[no_mangle]
pub extern "C" fn rt_math_fabs(x: f64) -> f64 { serp_math_fabs(x) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_log10(x: f64, out: *mut f64) -> i8 { st_f(serp_math_log10(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_log2(x: f64, out: *mut f64) -> i8 { st_f(serp_math_log2(x), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_log1p(x: f64, out: *mut f64) -> i8 { st_f(serp_math_log1p(x), out) }

#[no_mangle]
pub extern "C" fn rt_math_copysign(x: f64, y: f64) -> f64 { serp_math_copysign(x, y) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_fmod(x: f64, y: f64, out: *mut f64) -> i8 { st_f(serp_math_fmod(x, y), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_ldexp(x: f64, i: i64, out: *mut f64) -> i8 { st_f(serp_math_ldexp(x, i), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_trunc(x: f64, out: *mut i64) -> i8 { st_i(serp_math_trunc(x), out) }

#[no_mangle]
pub extern "C" fn rt_math_hypot(x: f64, y: f64) -> f64 { serp_math_hypot(x, y) }

#[no_mangle]
pub extern "C" fn rt_math_nextafter(x: f64, y: f64) -> f64 { serp_math_nextafter(x, y) }

#[no_mangle]
pub extern "C" fn rt_math_ulp(x: f64) -> f64 { serp_math_ulp(x) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_factorial(n: i64, out: *mut i64) -> i8 { st_i(serp_math_factorial(n), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_gcd(a: i64, b: i64, out: *mut i64) -> i8 { st_i(serp_math_gcd(a, b), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_lcm(a: i64, b: i64, out: *mut i64) -> i8 { st_i(serp_math_lcm(a, b), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_isqrt(n: i64, out: *mut i64) -> i8 { st_i(serp_math_isqrt(n), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_comb(n: i64, k: i64, out: *mut i64) -> i8 { st_i(serp_math_comb(n, k), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_math_perm(n: i64, k: i64, out: *mut i64) -> i8 { st_i(serp_math_perm(n, k), out) }

#[no_mangle]
pub extern "C" fn rt_math_frexp_m(x: f64) -> f64 { serp_math_frexp_m(x) }

#[no_mangle]
pub extern "C" fn rt_math_frexp_e(x: f64) -> i64 { serp_math_frexp_e(x) }

#[no_mangle]
pub extern "C" fn rt_math_modf_frac(x: f64) -> f64 { serp_math_modf_frac(x) }

#[no_mangle]
pub extern "C" fn rt_math_modf_int(x: f64) -> f64 { serp_math_modf_int(x) }

#[no_mangle]
pub extern "C" fn rt_rand_seed(n: i64) { serp_rand_seed(n) }

#[no_mangle]
pub extern "C" fn rt_rand_seed_sys() { serp_rand_seed_sys() }

#[no_mangle]
pub extern "C" fn rt_rand_random() -> f64 { serp_rand_random() }

#[no_mangle]
pub unsafe extern "C" fn rt_rand_getrandbits(k: i64, out: *mut i64) -> i8 { st_i(serp_rand_getrandbits(k), out) }

#[no_mangle]
pub extern "C" fn rt_rand_randbelow(n: i64) -> i64 { serp_rand_randbelow(n) }

#[no_mangle]
pub extern "C" fn rt_time_time() -> f64 { serp_time_time() }

#[no_mangle]
pub extern "C" fn rt_time_time_ns() -> i64 { serp_time_time_ns() }

#[no_mangle]
pub extern "C" fn rt_time_monotonic_ns() -> i64 { serp_time_monotonic_ns() }

#[no_mangle]
pub extern "C" fn rt_time_perf_counter() -> f64 { serp_time_perf_counter() }

#[no_mangle]
pub extern "C" fn rt_time_perf_counter_ns() -> i64 { serp_time_perf_counter_ns() }

#[no_mangle]
pub extern "C" fn rt_time_monotonic() -> f64 { serp_time_monotonic() }

#[no_mangle]
pub extern "C" fn rt_time_sleep(secs: f64) -> i8 {
    match serp_time_sleep(secs) { Ok(()) => 0, Err(e) => { set_pending(e); 1 } }
}
// ---------- rtlib: serp_os / serp_hashlib / serp_uuid / serp_secrets ----------

unsafe fn st_s(r: SRes<SStr>, out: *mut SStr) -> i8 {
    match r { Ok(v) => { out.write(v); 0 } Err(e) => { set_pending(e); 1 } }
}

unsafe fn st_n(r: SRes<()>) -> i8 {
    match r { Ok(()) => 0, Err(e) => { set_pending(e); 1 } }
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_getenv(name: *const SStr, out: *mut SStr) {
    out.write(serp_os_getenv(s(name)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_log_set(key: *const SStr, val: *const SStr) {
    serp_log_set(s(key), s(val));
}

#[no_mangle]
pub unsafe extern "C" fn rt_log_get(key: *const SStr, out: *mut SStr) {
    out.write(serp_log_get(s(key)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_log_write_err(line: *const SStr) {
    serp_log_write_err(s(line));
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_has_env(name: *const SStr) -> i8 {
    serp_os_has_env(s(name)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_setenv(name: *const SStr, value: *const SStr) -> i8 {
    st_n(serp_os_setenv(s(name), s(value)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_unsetenv(name: *const SStr) -> i8 {
    st_n(serp_os_unsetenv(s(name)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_getcwd(out: *mut SStr) -> i8 {
    st_s(serp_os_getcwd(), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_chdir(p: *const SStr) -> i8 {
    st_n(serp_os_chdir(s(p)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_exists(p: *const SStr) -> i8 {
    serp_os_exists(s(p)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_is_file(p: *const SStr) -> i8 {
    serp_os_is_file(s(p)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_is_dir(p: *const SStr) -> i8 {
    serp_os_is_dir(s(p)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_mkdir(p: *const SStr) -> i8 {
    st_n(serp_os_mkdir(s(p)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_rmdir(p: *const SStr) -> i8 {
    st_n(serp_os_rmdir(s(p)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_remove(p: *const SStr) -> i8 {
    st_n(serp_os_remove(s(p)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_os_listdir(p: *const SStr, out: *mut RtList) -> i8 {
    match serp_os_listdir(s(p)) {
        Ok(v) => { vec_sstr_to_rtlist(v, out); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_hash_sha256(a: *const SStr, out: *mut SStr) {
    out.write(serp_hash_sha256(s(a)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_hash_sha256_y(h: *const u8, out: *mut SStr) {
    out.write(serp_hash_sha256_y(&bview(h)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_hash_sha1_y(h: *const u8, out: *mut SStr) {
    out.write(serp_hash_sha1_y(&bview(h)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_hash_md5_y(h: *const u8, out: *mut SStr) {
    out.write(serp_hash_md5_y(&bview(h)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_hash_sha1(a: *const SStr, out: *mut SStr) {
    out.write(serp_hash_sha1(s(a)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_hash_md5(a: *const SStr, out: *mut SStr) {
    out.write(serp_hash_md5(s(a)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_uuid4(out: *mut SStr) {
    out.write(serp_uuid4());
}

#[no_mangle]
pub unsafe extern "C" fn rt_secrets_token_hex(n: i64, out: *mut SStr) -> i8 {
    st_s(serp_secrets_token_hex(n), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_secrets_token_urlsafe(n: i64, out: *mut SStr) -> i8 {
    st_s(serp_secrets_token_urlsafe(n), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_secrets_randbelow(n: i64, out: *mut i64) -> i8 {
    st_i(serp_secrets_randbelow(n), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_secrets_randbits(k: i64, out: *mut i64) -> i8 {
    st_i(serp_secrets_randbits(k), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_secrets_token_bytes(n: i64, out: *mut *const u8) -> i8 {
    st_y(serp_secrets_token_bytes(n), out)
}

// ---------- bytes / bytearray ABI ----------
// SBytes crosses the boundary as an opaque handle (*const u8 = Rc<Vec<u8>> raw).
// bytearray is an RtList of u8 (element size 1).

unsafe fn bview(h: *const u8) -> std::mem::ManuallyDrop<SBytes> {
    std::mem::ManuallyDrop::new(SBytes { v: Rc::from_raw(h as *const Vec<u8>) })
}

fn bout(b: SBytes) -> *const u8 {
    Rc::into_raw(b.v) as *const u8
}

unsafe fn ba_view(l: *const RtList) -> SByteArray {
    let v = if (*l).data.is_null() { Vec::new() } else {
        std::slice::from_raw_parts((*l).data, (*l).len as usize).to_vec()
    };
    SByteArray { v }
}

unsafe fn ba_take(l: *mut RtList) -> Vec<u8> {
    if (*l).data.is_null() { return Vec::new(); }
    Vec::from_raw_parts((*l).data, (*l).len as usize, (*l).cap as usize)
}

unsafe fn ba_put(l: *mut RtList, v: Vec<u8>) {
    let mut v = std::mem::ManuallyDrop::new(v);
    (*l).data = v.as_mut_ptr();
    (*l).len = v.len() as i64;
    (*l).cap = v.capacity() as i64;
}

unsafe fn slist_out_bytes(out: *mut RtList, items: Vec<SBytes>) {
    let mut hs: Vec<*const u8> = items.into_iter().map(bout).collect();
    let mut hs = std::mem::ManuallyDrop::new(hs);
    (*out).data = hs.as_mut_ptr() as *mut u8;
    (*out).len = hs.len() as i64;
    (*out).cap = hs.capacity() as i64;
}

unsafe fn slist_out_ints(out: *mut RtList, items: Vec<i64>) {
    let mut xs = std::mem::ManuallyDrop::new(items);
    (*out).data = xs.as_mut_ptr() as *mut u8;
    (*out).len = xs.len() as i64;
    (*out).cap = xs.capacity() as i64;
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_new(p: *const u8, len: i64) -> *const u8 {
    let v = if len == 0 { Vec::new() } else {
        std::slice::from_raw_parts(p, len as usize).to_vec()
    };
    bout(sbytes(v))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_clone(h: *const u8) {
    Rc::increment_strong_count(h as *const Vec<u8>);
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_drop(h: *const u8) {
    if h.is_null() {
        return;
    }
    drop(Rc::from_raw(h as *const Vec<u8>));
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_len(h: *const u8) -> i64 {
    bview(h).len_i()
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_index(h: *const u8, i: i64, out: *mut i64) -> i8 {
    match pyb_index(&bview(h), i) {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_slice(h: *const u8, lo: i64, has_lo: i8,
                                        hi: i64, has_hi: i8) -> *const u8 {
    let lo = if has_lo != 0 { Some(lo) } else { None };
    let hi = if has_hi != 0 { Some(hi) } else { None };
    bout(pyb_slice(&bview(h), lo, hi))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_concat(a: *const u8, b: *const u8) -> *const u8 {
    bout(pyb_concat(&bview(a), &bview(b)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_repeat(a: *const u8, k: i64) -> *const u8 {
    bout(pyb_repeat(&bview(a), k))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_eq(a: *const u8, b: *const u8) -> i8 {
    (*bview(a) == *bview(b)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_cmp(a: *const u8, b: *const u8) -> i32 {
    match bview(a).v.as_slice().cmp(bview(b).v.as_slice()) {
        std::cmp::Ordering::Less => -1,
        std::cmp::Ordering::Equal => 0,
        std::cmp::Ordering::Greater => 1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_contains(a: *const u8, b: *const u8) -> i8 {
    pyb_contains(&bview(a), &bview(b)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_find(a: *const u8, b: *const u8) -> i64 {
    pyb_find(&bview(a), &bview(b))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_count(a: *const u8, b: *const u8) -> i64 {
    pyb_count(&bview(a), &bview(b))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_startswith(a: *const u8, b: *const u8) -> i8 {
    pyb_startswith(&bview(a), &bview(b)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_endswith(a: *const u8, b: *const u8) -> i8 {
    pyb_endswith(&bview(a), &bview(b)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_replace(a: *const u8, f: *const u8, t: *const u8) -> *const u8 {
    bout(pyb_replace(&bview(a), &bview(f), &bview(t)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_strip(a: *const u8) -> *const u8 { bout(pyb_strip(&bview(a))) }
#[no_mangle]
pub unsafe extern "C" fn rt_bytes_lstrip(a: *const u8) -> *const u8 { bout(pyb_lstrip(&bview(a))) }
#[no_mangle]
pub unsafe extern "C" fn rt_bytes_rstrip(a: *const u8) -> *const u8 { bout(pyb_rstrip(&bview(a))) }
#[no_mangle]
pub unsafe extern "C" fn rt_bytes_upper(a: *const u8) -> *const u8 { bout(pyb_upper(&bview(a))) }
#[no_mangle]
pub unsafe extern "C" fn rt_bytes_lower(a: *const u8) -> *const u8 { bout(pyb_lower(&bview(a))) }

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_hex(a: *const u8, out: *mut SStr) {
    out.write(pyb_hex(&bview(a)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_decode(a: *const u8, out: *mut SStr) -> i8 {
    match pyb_decode(&bview(a)) {
        Ok(s) => { out.write(s); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_fromhex(sp: *const SStr, out: *mut *const u8) -> i8 {
    match pyb_fromhex(s(sp)) {
        Ok(b) => { out.write(bout(b)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_encode(sp: *const SStr) -> *const u8 {
    bout(py_str_encode(s(sp)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_from_ints(xs: *const RtList, out: *mut *const u8) -> i8 {
    let v: Vec<i64> = if (*xs).data.is_null() { Vec::new() } else {
        std::slice::from_raw_parts((*xs).data as *const i64, (*xs).len as usize).to_vec()
    };
    match pyb_from_ints(&v) {
        Ok(b) => { out.write(bout(b)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_zeros(n: i64, out: *mut *const u8) -> i8 {
    match pyb_zeros(n) {
        Ok(b) => { out.write(bout(b)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_split(a: *const u8, sep: *const u8, out: *mut RtList) -> i8 {
    match pyb_split(&bview(a), &bview(sep)) {
        Ok(items) => { slist_out_bytes(out, items); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_split_ws(a: *const u8, out: *mut RtList) {
    slist_out_bytes(out, pyb_split_ws(&bview(a)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_join(sep: *const u8, items: *const RtList) -> *const u8 {
    let hs: &[*const u8] = if (*items).data.is_null() { &[] } else {
        std::slice::from_raw_parts((*items).data as *const *const u8, (*items).len as usize)
    };
    let mut v = Vec::new();
    for (i, &h) in hs.iter().enumerate() {
        if i > 0 { v.extend_from_slice(&bview(sep).v); }
        v.extend_from_slice(&bview(h).v);
    }
    bout(sbytes(v))
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_ints(a: *const u8, out: *mut RtList) {
    slist_out_ints(out, pyb_ints(&bview(a)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_repr(a: *const u8, out: *mut SStr) {
    out.write(sstr(&bytes_repr(&bview(a).v)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_push(l: *mut RtList, x: i64) -> i8 {
    let mut ba = SByteArray { v: ba_take(l) };
    let r = ba.push_i(x);
    ba_put(l, ba.v);
    match r { Ok(()) => 0, Err(e) => { set_pending(e); 1 } }
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_extend_b(l: *mut RtList, h: *const u8) {
    let mut v = ba_take(l);
    v.extend_from_slice(&bview(h).v);
    ba_put(l, v);
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_extend_a(l: *mut RtList, o: *const RtList) {
    let mut v = ba_take(l);
    v.extend_from_slice(&ba_view(o).v);
    ba_put(l, v);
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_get(l: *const RtList, i: i64, out: *mut i64) -> i8 {
    match ba_view(l).get(i) {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_set(l: *mut RtList, i: i64, x: i64) -> i8 {
    let mut ba = SByteArray { v: ba_take(l) };
    let r = ba.set(i, x);
    ba_put(l, ba.v);
    match r { Ok(()) => 0, Err(e) => { set_pending(e); 1 } }
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_slice(l: *const RtList, lo: i64, has_lo: i8,
                                     hi: i64, has_hi: i8, out: *mut RtList) {
    let lo = if has_lo != 0 { Some(lo) } else { None };
    let hi = if has_hi != 0 { Some(hi) } else { None };
    let r = pyba_slice(&ba_view(l), lo, hi);
    ba_put(out, r.v);
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_to_bytes(l: *const RtList) -> *const u8 {
    bout(ba_view(l).as_bytes())
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_from_bytes(h: *const u8, out: *mut RtList) {
    ba_put(out, bview(h).v.as_ref().clone());
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_from_ints(xs: *const RtList, out: *mut RtList) -> i8 {
    let v: Vec<i64> = if (*xs).data.is_null() { Vec::new() } else {
        std::slice::from_raw_parts((*xs).data as *const i64, (*xs).len as usize).to_vec()
    };
    match pyba_from_ints(&v) {
        Ok(b) => { ba_put(out, b.v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_zeros(n: i64, out: *mut RtList) -> i8 {
    match pyba_zeros(n) {
        Ok(b) => { ba_put(out, b.v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_eq(a: *const RtList, b: *const RtList) -> i8 {
    (ba_view(a).v == ba_view(b).v) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_clone(src: *const RtList, dst: *mut RtList) {
    ba_put(dst, ba_view(src).v);
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_hex(l: *const RtList, out: *mut SStr) {
    out.write(pyb_hex(&ba_view(l).as_bytes()));
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_decode(l: *const RtList, out: *mut SStr) -> i8 {
    match pyb_decode(&ba_view(l).as_bytes()) {
        Ok(s2) => { out.write(s2); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_repr(l: *const RtList, out: *mut SStr) {
    out.write(sstr(&ba_view(l).py_repr()));
}

#[no_mangle]
pub unsafe extern "C" fn rt_ba_ints(l: *const RtList, out: *mut RtList) {
    slist_out_ints(out, pyba_ints(&ba_view(l)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_file_read_bytes(f: *mut SerpFile, out: *mut *const u8) -> i8 {
    match (*f).read_all_bytes() {
        Ok(b) => { out.write(bout(b)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_file_write_bytes(f: *mut SerpFile, b: *const u8, out: *mut i64) -> i8 {
    match (*f).write_bytes(&bview(b).v) {
        Ok(n) => { out.write(n); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_file_write_ba(f: *mut SerpFile, l: *const RtList, out: *mut i64) -> i8 {
    match (*f).write_bytes(&ba_view(l).v) {
        Ok(n) => { out.write(n); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

// ---------- rtlib: serp_zlib ----------

unsafe fn st_y(r: SRes<SBytes>, out: *mut *const u8) -> i8 {
    match r {
        Ok(v) => { out.write(bout(v)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_crc32(h: *const u8) -> i64 {
    serp_zlib_crc32(&bview(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_crc32_seeded(h: *const u8, value: i64) -> i64 {
    serp_zlib_crc32_seeded(&bview(h), value)
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_adler32_seeded(h: *const u8, value: i64) -> i64 {
    serp_zlib_adler32_seeded(&bview(h), value)
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_adler32(h: *const u8) -> i64 {
    serp_zlib_adler32(&bview(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_compress(h: *const u8, level: i64, out: *mut *const u8) -> i8 {
    st_y(serp_zlib_compress(&bview(h), level), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_decompress(h: *const u8, out: *mut *const u8) -> i8 {
    st_y(serp_zlib_decompress(&bview(h)), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_deflate(h: *const u8, level: i64, out: *mut *const u8) -> i8 {
    st_y(serp_zlib_deflate(&bview(h), level), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_inflate(h: *const u8, out: *mut *const u8) -> i8 {
    st_y(serp_zlib_inflate(&bview(h)), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_gzip_compress(h: *const u8, level: i64, out: *mut *const u8) -> i8 {
    st_y(serp_zlib_gzip_compress(&bview(h), level), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_zlib_gzip_decompress(h: *const u8, out: *mut *const u8) -> i8 {
    st_y(serp_zlib_gzip_decompress(&bview(h)), out)
}

// ---------- rtlib: serp_sqlite ----------

unsafe fn st_i64(r: SRes<i64>, out: *mut i64) -> i8 {
    match r {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

unsafe fn st_f64(r: SRes<f64>, out: *mut f64) -> i8 {
    match r {
        Ok(v) => { out.write(v); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_open(path: *const SStr, out: *mut i64) -> i8 {
    st_i64(serp_sqlite_open(s(path)), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_close(h: i64) -> i8 {
    st_n(serp_sqlite_close(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_execute(h: i64, sql: *const SStr) -> i8 {
    st_n(serp_sqlite_execute(h, s(sql)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_changes(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sqlite_changes(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_last_rowid(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sqlite_last_rowid(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_prepare(h: i64, sql: *const SStr, out: *mut i64) -> i8 {
    st_i64(serp_sqlite_prepare(h, s(sql)), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_bind_int(h: i64, idx: i64, v: i64) -> i8 {
    st_n(serp_sqlite_bind_int(h, idx, v))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_bind_float(h: i64, idx: i64, v: f64) -> i8 {
    st_n(serp_sqlite_bind_float(h, idx, v))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_bind_text(h: i64, idx: i64, v: *const SStr) -> i8 {
    st_n(serp_sqlite_bind_text(h, idx, s(v)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_bind_blob(h: i64, idx: i64, v: *const u8) -> i8 {
    st_n(serp_sqlite_bind_blob(h, idx, &bview(v)))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_bind_null(h: i64, idx: i64) -> i8 {
    st_n(serp_sqlite_bind_null(h, idx))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_step(h: i64, out: *mut i8) -> i8 {
    match serp_sqlite_step(h) {
        Ok(v) => { out.write(v as i8); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_column_count(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sqlite_column_count(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_col_type(h: i64, i: i64, out: *mut i64) -> i8 {
    st_i64(serp_sqlite_col_type(h, i), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_col_int(h: i64, i: i64, out: *mut i64) -> i8 {
    st_i64(serp_sqlite_col_int(h, i), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_col_float(h: i64, i: i64, out: *mut f64) -> i8 {
    st_f64(serp_sqlite_col_float(h, i), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_col_text(h: i64, i: i64, out: *mut SStr) -> i8 {
    st_s(serp_sqlite_col_text(h, i), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_col_blob(h: i64, i: i64, out: *mut *const u8) -> i8 {
    st_y(serp_sqlite_col_blob(h, i), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_reset(h: i64) -> i8 {
    st_n(serp_sqlite_reset(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sqlite_finalize(h: i64) -> i8 {
    st_n(serp_sqlite_finalize(h))
}

// ---------- rtlib: serp_socket ----------

#[no_mangle]
pub unsafe extern "C" fn rt_sock_connect(host: *const SStr, port: i64, timeout_ms: i64,
                                         out: *mut i64) -> i8 {
    st_i64(serp_sock_connect(s(host), port, timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_tls_connect(host: *const SStr, port: i64, timeout_ms: i64,
                                             insecure: i64, out: *mut i64) -> i8 {
    st_i64(serp_sock_tls_connect(s(host), port, timeout_ms, insecure), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_listen(host: *const SStr, port: i64, out: *mut i64) -> i8 {
    st_i64(serp_sock_listen(s(host), port), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_accept(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sock_accept(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_send(h: i64, data: *const u8, out: *mut i64) -> i8 {
    st_i64(serp_sock_send(h, &bview(data)), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_send_all(h: i64, data: *const u8, timeout_ms: i64,
                                          out: *mut i64) -> i8 {
    st_i64(serp_sock_send_all(h, &bview(data), timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_recv(h: i64, maxlen: i64, out: *mut *const u8) -> i8 {
    st_y(serp_sock_recv(h, maxlen), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_shutdown_write(h: i64) -> i8 {
    st_n(serp_sock_shutdown_write(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_set_timeout(h: i64, ms: i64) -> i8 {
    st_n(serp_sock_set_timeout(h, ms))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_set_nonblocking(h: i64) -> i8 {
    st_n(serp_sock_set_nonblocking(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_set_async(h: i64) -> i8 {
    st_n(serp_sock_set_async(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_accept_nb(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sock_accept_nb(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_poll_ready(packed: *const u8, timeout_ms: i64,
                                            out: *mut *const u8) -> i8 {
    st_y(serp_sock_poll_ready(&bview(packed), timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_local_port(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sock_local_port(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_close(h: i64) -> i8 {
    st_n(serp_sock_close(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_udp_bind(host: *const SStr, port: i64, out: *mut i64) -> i8 {
    st_i64(serp_sock_udp_bind(s(host), port), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_udp_send_to(h: i64, data: *const u8, host: *const SStr,
                                             port: i64, out: *mut i64) -> i8 {
    st_i64(serp_sock_udp_send_to(h, &bview(data), s(host), port), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_udp_recv_from(h: i64, maxlen: i64, out: *mut *const u8) -> i8 {
    st_y(serp_sock_udp_recv_from(h, maxlen), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_udp_peer_host(h: i64, out: *mut SStr) -> i8 {
    st_s(serp_sock_udp_peer_host(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sock_udp_peer_port(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sock_udp_peer_port(h), out)
}

// ---------- PyVal (boxed dynamic values; handle = Rc<PValRepr> raw pointer) ----------

unsafe fn pview(h: *const u8) -> std::mem::ManuallyDrop<PVal> {
    std::mem::ManuallyDrop::new(PVal(Rc::from_raw(h as *const PValRepr)))
}

fn pout(v: PVal) -> *const u8 {
    Rc::into_raw(v.0) as *const u8
}

unsafe fn vec_pyval_to_rtlist(v: Vec<PVal>, out: *mut RtList) {
    let mut handles = std::mem::ManuallyDrop::new(
        v.into_iter().map(pout).collect::<Vec<*const u8>>());
    out.write(RtList {
        data: handles.as_mut_ptr() as *mut u8,
        len: handles.len() as i64,
        cap: handles.capacity() as i64,
    });
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_none() -> *const u8 { pout(pyval_none()) }

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_bool(b: i8) -> *const u8 { pout(pyval_bool(b != 0)) }

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_int(i: i64) -> *const u8 { pout(pyval_int(i)) }

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_float(f: f64) -> *const u8 { pout(pyval_float(f)) }

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_str(sp: *const SStr) -> *const u8 {
    pout(pyval_str((*sp).clone()))
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_bytes(h: *const u8) -> *const u8 {
    pout(pyval_bytes((*bview(h)).clone()))
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_list_new() -> *const u8 { pout(pyval_list(Vec::new())) }

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_list_push(h: *const u8, item: *const u8) {
    let mut rc = std::mem::ManuallyDrop::new(Rc::from_raw(h as *const PValRepr));
    if let Some(PValRepr::List(v)) = Rc::get_mut(&mut *rc) {
        v.push((*pview(item)).clone());
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_dict_new() -> *const u8 {
    pout(pyval_dict(SerpDict::new()))
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_dict_set(h: *const u8, k: *const SStr, val: *const u8) {
    let mut rc = std::mem::ManuallyDrop::new(Rc::from_raw(h as *const PValRepr));
    if let Some(PValRepr::Dict(d)) = Rc::get_mut(&mut *rc) {
        d.set(pyval_str((*k).clone()), (*pview(val)).clone());
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_dict_set_pv(h: *const u8, k: *const u8, val: *const u8) {
    let mut rc = std::mem::ManuallyDrop::new(Rc::from_raw(h as *const PValRepr));
    if let Some(PValRepr::Dict(d)) = Rc::get_mut(&mut *rc) {
        d.set((*pview(k)).clone(), (*pview(val)).clone());
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_clone(h: *const u8) {
    Rc::increment_strong_count(h as *const PValRepr);
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_drop(h: *const u8) {
    if h.is_null() {
        return;
    }
    drop(Rc::from_raw(h as *const PValRepr));
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_kind(h: *const u8, out: *mut SStr) {
    out.write(pyval_kind(&*pview(h)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_json(h: *const u8, ensure_ascii: i8, compact: i8,
                                       out: *mut SStr) -> i8 {
    match pyval_json(&*pview(h), ensure_ascii != 0, compact != 0) {
        Ok(s) => {
            out.write(s);
            0
        }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_truthy(h: *const u8) -> i8 {
    pyval_truthy(&*pview(h)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_eq(a: *const u8, b: *const u8) -> i8 {
    pyval_eq(&*pview(a), &*pview(b)) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_len(h: *const u8, out: *mut i64) -> i8 {
    match pyval_len(&*pview(h)) {
        Ok(n) => { out.write(n); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_getitem_i(h: *const u8, i: i64, out: *mut *const u8) -> i8 {
    match pyval_getitem_i(&*pview(h), i) {
        Ok(v) => { out.write(pout(v)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_getitem_s(h: *const u8, k: *const SStr,
                                            out: *mut *const u8) -> i8 {
    match pyval_getitem_s(&*pview(h), &*k) {
        Ok(v) => { out.write(pout(v)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_getitem_v(h: *const u8, k: *const u8,
                                            out: *mut *const u8) -> i8 {
    match pyval_getitem_v(&*pview(h), &*pview(k)) {
        Ok(v) => { out.write(pout(v)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_contains(h: *const u8, n: *const u8, out: *mut i8) -> i8 {
    match pyval_contains(&*pview(h), &*pview(n)) {
        Ok(b) => { out.write(b as i8); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_iter(h: *const u8, out: *mut RtList) -> i8 {
    match pyval_iter(&*pview(h)) {
        Ok(v) => { vec_pyval_to_rtlist(v, out); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_to_int(h: *const u8, out: *mut i64) -> i8 {
    match pyval_to_int(&*pview(h)) {
        Ok(i) => { out.write(i); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_to_float(h: *const u8, out: *mut f64) -> i8 {
    match pyval_to_float(&*pview(h)) {
        Ok(f) => { out.write(f); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_to_bytes(h: *const u8, out: *mut *const u8) -> i8 {
    match pyval_to_bytes(&*pview(h)) {
        Ok(b) => { out.write(bout(b)); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_str_of(h: *const u8, out: *mut SStr) {
    out.write(sstring(pview(h).py_str()));
}

#[no_mangle]
pub unsafe extern "C" fn rt_pyval_repr(h: *const u8, out: *mut SStr) {
    out.write(sstring(pview(h).py_repr()));
}

// ---------- threads (DECISIONS.md D9: Send-checked spawn/join) ----------

struct SendPtr(*mut u8);
unsafe impl Send for SendPtr {}

struct RtThread {
    h: Option<std::thread::JoinHandle<SendPtr>>,
}

enum RtThreadRes {
    Ok(i64),
    Err(String, String),
}

#[no_mangle]
pub unsafe extern "C" fn rt_buf_alloc(n: i64) -> *mut u8 {
    rust_alloc(Layout::from_size_align(n.max(8) as usize, 8).unwrap())
}

#[no_mangle]
pub unsafe extern "C" fn rt_buf_free(p: *mut u8, n: i64) {
    rust_dealloc(p, Layout::from_size_align(n.max(8) as usize, 8).unwrap());
}

// Consumes the SStr blob; produces a Send box for the thread boundary.
#[no_mangle]
pub unsafe extern "C" fn rt_str_send(p: *mut SStr) -> *mut u8 {
    let s = std::ptr::read(p);
    let out = s.as_str().to_string();
    drop(s);
    Box::into_raw(Box::new(out)) as *mut u8
}

#[no_mangle]
pub unsafe extern "C" fn rt_str_recv(p: *mut u8, out: *mut SStr) {
    let s = Box::from_raw(p as *mut String);
    out.write(sstring(*s));
}

// Consumes the bytes handle; produces a Send box for the thread boundary.
#[no_mangle]
pub unsafe extern "C" fn rt_bytes_send(h: *const u8) -> *mut u8 {
    let rc = Rc::from_raw(h as *const Vec<u8>);
    let v = (*rc).clone();
    drop(rc);
    Box::into_raw(Box::new(v)) as *mut u8
}

#[no_mangle]
pub unsafe extern "C" fn rt_bytes_recv(p: *mut u8) -> *const u8 {
    let v = Box::from_raw(p as *mut Vec<u8>);
    Rc::into_raw(Rc::new(*v)) as *const u8
}

#[no_mangle]
pub unsafe extern "C" fn rt_box_ok(payload: i64) -> *mut u8 {
    Box::into_raw(Box::new(RtThreadRes::Ok(payload))) as *mut u8
}

// Takes the thread-local pending error into a Send result box.
#[no_mangle]
pub unsafe extern "C" fn rt_box_err() -> *mut u8 {
    let e = take_pending();
    Box::into_raw(Box::new(RtThreadRes::Err(e.kind, e.msg))) as *mut u8
}

#[no_mangle]
pub unsafe extern "C" fn rt_thread_spawn(f: extern "C" fn(*mut u8) -> *mut u8,
                                         env: *mut u8) -> *mut u8 {
    let env = SendPtr(env);
    let h = serp_thread_spawn(move || {
        let env = env;
        SendPtr(f(env.0))
    });
    Box::into_raw(Box::new(RtThread { h: Some(h) })) as *mut u8
}

#[no_mangle]
pub unsafe extern "C" fn rt_thread_join(hp: *mut u8, out: *mut i64) -> i8 {
    let t = &mut *(hp as *mut RtThread);
    match t.h.take() {
        None => {
            set_pending(SerpErr::new("ValueError", "thread already joined".to_string()));
            1
        }
        Some(j) => match j.join() {
            Err(_) => {
                set_pending(SerpErr::new("RuntimeError", "thread panicked".to_string()));
                1
            }
            Ok(p) => {
                let res = Box::from_raw(p.0 as *mut RtThreadRes);
                match *res {
                    RtThreadRes::Ok(v) => { *out = v; 0 }
                    RtThreadRes::Err(k, m) => { set_pending(SerpErr::new(&k, m)); 1 }
                }
            }
        },
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_thread_drop(hp: *mut u8) {
    drop(Box::from_raw(hp as *mut RtThread));
}

// ---------- asyncio tasks (D45) + rtlib: _serp_asyncio ----------

struct RtTask {
    tid: usize,
    slot: Arc<Mutex<Option<SendPtr>>>,
}

#[no_mangle]
pub unsafe extern "C" fn rt_task_spawn(f: extern "C" fn(*mut u8) -> *mut u8,
                                       env: *mut u8) -> *mut u8 {
    let env = SendPtr(env);
    let slot: Arc<Mutex<Option<SendPtr>>> = Arc::new(Mutex::new(None));
    let s2 = slot.clone();
    let tid = aio_task_spawn(Box::new(move || {
        let env = env;
        let r = SendPtr(f(env.0));
        *lock_ok(&s2) = Some(r);
    }));
    Box::into_raw(Box::new(RtTask { tid, slot })) as *mut u8
}

#[no_mangle]
pub unsafe extern "C" fn rt_task_await(hp: *mut u8, out: *mut i64) -> i8 {
    let t = &*(hp as *const RtTask);
    aio_task_wait(t.tid);
    let taken = lock_ok(&t.slot).take();
    match taken {
        None => {
            set_pending(SerpErr::new("RuntimeError", "task result already taken".to_string()));
            1
        }
        Some(p) => {
            let res = Box::from_raw(p.0 as *mut RtThreadRes);
            match *res {
                RtThreadRes::Ok(v) => { *out = v; 0 }
                RtThreadRes::Err(k, m) => { set_pending(SerpErr::new(&k, m)); 1 }
            }
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_task_done(hp: *mut u8) -> i8 {
    let t = &*(hp as *const RtTask);
    aio_task_done(t.tid) as i8
}

#[no_mangle]
pub unsafe extern "C" fn rt_task_drop(hp: *mut u8) {
    drop(Box::from_raw(hp as *mut RtTask));
}

#[no_mangle]
pub extern "C" fn rt_aio_sleep(secs: f64) -> i8 {
    match serp_aio_sleep(secs) { Ok(()) => 0, Err(e) => { set_pending(e); 1 } }
}

#[no_mangle]
pub extern "C" fn rt_aio_current() -> i64 { serp_aio_current() }

#[no_mangle]
pub unsafe extern "C" fn rt_aio_park() -> i8 { st_n(serp_aio_park()) }

#[no_mangle]
pub unsafe extern "C" fn rt_aio_wake(tid: i64) -> i8 { st_n(serp_aio_wake(tid)) }

#[no_mangle]
pub unsafe extern "C" fn rt_aio_wait_fd(h: i64, write: i64, timeout_ms: i64, out: *mut i8) -> i8 {
    st_b(serp_aio_wait_fd(h, write, timeout_ms), out)
}

#[no_mangle]
pub extern "C" fn rt_aio_running() -> i8 { serp_aio_running() as i8 }

#[no_mangle]
pub unsafe extern "C" fn rt_aio_ev_new() -> i64 { serp_aio_ev_new() }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_ev_set(h: i64) -> i8 { st_n(serp_aio_ev_set(h)) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_ev_clear(h: i64) -> i8 { st_n(serp_aio_ev_clear(h)) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_ev_is_set(h: i64, out: *mut i8) -> i8 { st_b(serp_aio_ev_is_set(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_ev_wait(h: i64, out: *mut i8) -> i8 { st_b(serp_aio_ev_wait(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_lock_new() -> i64 { serp_aio_lock_new() }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_lock_acquire(h: i64, out: *mut i8) -> i8 { st_b(serp_aio_lock_acquire(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_lock_release(h: i64) -> i8 { st_n(serp_aio_lock_release(h)) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_lock_locked(h: i64, out: *mut i8) -> i8 { st_b(serp_aio_lock_locked(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_sem_new(v: i64, out: *mut i64) -> i8 { st_i64(serp_aio_sem_new(v), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_sem_acquire(h: i64, out: *mut i8) -> i8 { st_b(serp_aio_sem_acquire(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_sem_release(h: i64, bounded: i64, initial: i64) -> i8 {
    st_n(serp_aio_sem_release(h, bounded, initial))
}
#[no_mangle]
pub unsafe extern "C" fn rt_aio_sem_locked(h: i64, out: *mut i8) -> i8 { st_b(serp_aio_sem_locked(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_sem_value(h: i64, out: *mut i64) -> i8 { st_i64(serp_aio_sem_value(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_q_new(maxsize: i64) -> i64 { serp_aio_q_new(maxsize) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_q_put(h: i64, item: *const u8, nowait: i64, out: *mut i8) -> i8 {
    st_b(serp_aio_q_put(h, &pv_arg(item), nowait), out)
}
#[no_mangle]
pub unsafe extern "C" fn rt_aio_q_get(h: i64, nowait: i64, out: *mut i8) -> i8 {
    st_b(serp_aio_q_get(h, nowait), out)
}
#[no_mangle]
pub unsafe extern "C" fn rt_aio_q_qsize(h: i64, out: *mut i64) -> i8 { st_i64(serp_aio_q_qsize(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_q_maxsize(h: i64, out: *mut i64) -> i8 { st_i64(serp_aio_q_maxsize(h), out) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_q_task_done(h: i64) -> i8 { st_n(serp_aio_q_task_done(h)) }
#[no_mangle]
pub unsafe extern "C" fn rt_aio_q_join(h: i64) -> i8 { st_n(serp_aio_q_join(h)) }

// ---------- rtlib: serp_subprocess ----------

#[no_mangle]
pub unsafe extern "C" fn rt_sp_spawn(argv: *const SStr, cwd: *const SStr, env: *const SStr,
                                     flags: i64, out: *mut i64) -> i8 {
    st_i64(serp_sp_spawn(s(argv), s(cwd), s(env), flags), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_pid(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sp_pid(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_communicate(h: i64, input: *const u8, has_input: i64,
                                           timeout_ms: i64, out: *mut i8) -> i8 {
    match serp_sp_communicate(h, &bview(input), has_input, timeout_ms) {
        Ok(v) => { out.write(v as i8); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_wait(h: i64, timeout_ms: i64, out: *mut i8) -> i8 {
    match serp_sp_wait(h, timeout_ms) {
        Ok(v) => { out.write(v as i8); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_poll(h: i64, out: *mut i8) -> i8 {
    match serp_sp_poll(h) {
        Ok(v) => { out.write(v as i8); 0 }
        Err(e) => { set_pending(e); 1 }
    }
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_returncode(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_sp_returncode(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_stdout(h: i64, out: *mut *const u8) -> i8 {
    st_y(serp_sp_stdout(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_stderr(h: i64, out: *mut *const u8) -> i8 {
    st_y(serp_sp_stderr(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_kill(h: i64) -> i8 {
    st_n(serp_sp_kill(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_terminate(h: i64) -> i8 {
    st_n(serp_sp_terminate(h))
}

#[no_mangle]
pub unsafe extern "C" fn rt_sp_free(h: i64) -> i8 {
    st_n(serp_sp_free(h))
}

// ---------- Thread objects (D9 v2) + rtlib: serp_threading_core / serp_queue_core ----------

unsafe fn thv(h: *mut u8) -> std::mem::ManuallyDrop<SThread> {
    std::mem::ManuallyDrop::new(Arc::from_raw(h as *const ThreadRec))
}

unsafe fn pv_arg(h: *const u8) -> std::mem::ManuallyDrop<PVal> { pview(h) }

unsafe fn st_p(r: PVal, out: *mut *const u8) { out.write(pout(r)); }

unsafe fn st_b(r: SRes<bool>, out: *mut i8) -> i8 {
    match r { Ok(v) => { out.write(v as i8); 0 } Err(e) => { set_pending(e); 1 } }
}

#[no_mangle]
pub unsafe extern "C" fn rt_thread_new(f: extern "C" fn(*mut u8) -> *mut u8, env: *mut u8,
                                       name: *const SStr, has_name: i64, daemon: i8,
                                       delay_ms: i64, target: *const SStr) -> *mut u8 {
    let env = SendPtr(env);
    let body: ThreadBody = Box::new(move || {
        let env = env;
        let res = Box::from_raw(f(env.0) as *mut RtThreadRes);
        match *res {
            RtThreadRes::Ok(_) => Ok(()),
            RtThreadRes::Err(k, m) => Err((k, m)),
        }
    });
    let nm = if has_name != 0 { Some(s(name).to_string()) } else { None };
    let t = serp_thread_new(body, nm, daemon != 0, delay_ms, s(target));
    Arc::into_raw(t) as *mut u8
}

#[no_mangle]
pub unsafe extern "C" fn rt_thread_start(h: *mut u8) -> i8 { st_n(serp_thread_start(&thv(h))) }

#[no_mangle]
pub unsafe extern "C" fn rt_thread_join_t(h: *mut u8, timeout_ms: i64) -> i8 {
    st_n(serp_thread_join(&thv(h), timeout_ms))
}

#[no_mangle]
pub unsafe extern "C" fn rt_thread_alive(h: *mut u8) -> i8 { serp_thread_is_alive(&thv(h)) as i8 }

#[no_mangle]
pub unsafe extern "C" fn rt_thread_name(h: *mut u8, out: *mut SStr) {
    out.write(serp_thread_name(&thv(h)));
}

#[no_mangle]
pub unsafe extern "C" fn rt_thread_set_name(h: *mut u8, name: *const SStr) {
    serp_thread_set_name(&thv(h), s(name));
}

#[no_mangle]
pub unsafe extern "C" fn rt_thread_ident(h: *mut u8) -> i64 { serp_thread_ident(&thv(h)) }

#[no_mangle]
pub unsafe extern "C" fn rt_thread_daemon(h: *mut u8) -> i8 { serp_thread_daemon(&thv(h)) as i8 }

#[no_mangle]
pub unsafe extern "C" fn rt_thread_cancel(h: *mut u8) { serp_thread_cancel(&thv(h)); }

#[no_mangle]
pub unsafe extern "C" fn rt_thread_free(h: *mut u8) {
    drop(Arc::from_raw(h as *const ThreadRec));
}

#[no_mangle]
pub unsafe extern "C" fn rt_threads_join_all() { serp_threads_join_all(); }

#[no_mangle]
pub unsafe extern "C" fn rt_th_ident() -> i64 { serp_th_ident() }

#[no_mangle]
pub unsafe extern "C" fn rt_th_name(out: *mut SStr) { out.write(serp_th_name()); }

#[no_mangle]
pub unsafe extern "C" fn rt_th_active_count() -> i64 { serp_th_active_count() }

#[no_mangle]
pub unsafe extern "C" fn rt_th_main_ident() -> i64 { serp_th_main_ident() }

#[no_mangle]
pub unsafe extern "C" fn rt_tls_set(key: *const SStr, val: *const u8) {
    serp_tls_set(s(key), &pv_arg(val));
}

#[no_mangle]
pub unsafe extern "C" fn rt_tls_get(key: *const SStr, out: *mut *const u8) {
    st_p(serp_tls_get(s(key)), out);
}

#[no_mangle]
pub unsafe extern "C" fn rt_tls_has(key: *const SStr) -> i8 { serp_tls_has(s(key)) as i8 }

#[no_mangle]
pub unsafe extern "C" fn rt_tls_del(key: *const SStr) -> i8 { serp_tls_del(s(key)) as i8 }

#[no_mangle]
pub unsafe extern "C" fn rt_lock_new() -> i64 { serp_lock_new() }

#[no_mangle]
pub unsafe extern "C" fn rt_lock_acquire(h: i64, timeout_ms: i64, reentrant: i64, out: *mut i8) -> i8 {
    st_b(serp_lock_acquire(h, timeout_ms, reentrant), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_lock_release(h: i64, reentrant: i64) -> i8 {
    st_n(serp_lock_release(h, reentrant))
}

#[no_mangle]
pub unsafe extern "C" fn rt_lock_locked(h: i64, out: *mut i8) -> i8 { st_b(serp_lock_locked(h), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_lock_owned(h: i64, out: *mut i8) -> i8 { st_b(serp_lock_owned(h), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_event_new() -> i64 { serp_event_new() }

#[no_mangle]
pub unsafe extern "C" fn rt_event_set(h: i64) -> i8 { st_n(serp_event_set(h)) }

#[no_mangle]
pub unsafe extern "C" fn rt_event_clear(h: i64) -> i8 { st_n(serp_event_clear(h)) }

#[no_mangle]
pub unsafe extern "C" fn rt_event_is_set(h: i64, out: *mut i8) -> i8 { st_b(serp_event_is_set(h), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_event_wait(h: i64, timeout_ms: i64, out: *mut i8) -> i8 {
    st_b(serp_event_wait(h, timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sem_new(value: i64, out: *mut i64) -> i8 { st_i64(serp_sem_new(value), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_sem_acquire(h: i64, timeout_ms: i64, out: *mut i8) -> i8 {
    st_b(serp_sem_acquire(h, timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_sem_release(h: i64, n: i64) -> i8 { st_n(serp_sem_release(h, n)) }

#[no_mangle]
pub unsafe extern "C" fn rt_sem_value(h: i64, out: *mut i64) -> i8 { st_i64(serp_sem_value(h), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_cond_new() -> i64 { serp_cond_new() }

#[no_mangle]
pub unsafe extern "C" fn rt_cond_wait(h: i64, lock_h: i64, timeout_ms: i64, out: *mut i8) -> i8 {
    st_b(serp_cond_wait(h, lock_h, timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_cond_notify(h: i64, n: i64) -> i8 { st_n(serp_cond_notify(h, n)) }

#[no_mangle]
pub unsafe extern "C" fn rt_barrier_new(parties: i64, out: *mut i64) -> i8 {
    st_i64(serp_barrier_new(parties), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_barrier_wait(h: i64, timeout_ms: i64, out: *mut i64) -> i8 {
    st_i64(serp_barrier_wait(h, timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_barrier_reset(h: i64) -> i8 { st_n(serp_barrier_reset(h)) }

#[no_mangle]
pub unsafe extern "C" fn rt_barrier_abort(h: i64) -> i8 { st_n(serp_barrier_abort(h)) }

#[no_mangle]
pub unsafe extern "C" fn rt_barrier_parties(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_barrier_parties(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_barrier_n_waiting(h: i64, out: *mut i64) -> i8 {
    st_i64(serp_barrier_n_waiting(h), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_barrier_broken(h: i64, out: *mut i8) -> i8 { st_b(serp_barrier_broken(h), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_q_new(maxsize: i64, lifo: i64) -> i64 { serp_q_new(maxsize, lifo) }

#[no_mangle]
pub unsafe extern "C" fn rt_q_put(h: i64, item: *const u8, block: i64, timeout_ms: i64, out: *mut i8) -> i8 {
    st_b(serp_q_put(h, &pv_arg(item), block, timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_q_get(h: i64, block: i64, timeout_ms: i64, out: *mut i8) -> i8 {
    st_b(serp_q_get(h, block, timeout_ms), out)
}

#[no_mangle]
pub unsafe extern "C" fn rt_q_last(out: *mut *const u8) { st_p(serp_q_last(), out); }

#[no_mangle]
pub unsafe extern "C" fn rt_q_qsize(h: i64, out: *mut i64) -> i8 { st_i64(serp_q_qsize(h), out) }

#[no_mangle]
pub unsafe extern "C" fn rt_q_task_done(h: i64) -> i8 { st_n(serp_q_task_done(h)) }

#[no_mangle]
pub unsafe extern "C" fn rt_q_join(h: i64) -> i8 { st_n(serp_q_join(h)) }
