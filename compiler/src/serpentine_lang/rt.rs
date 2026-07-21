// Serpentine LLVM-backend runtime ABI (Phase 5). This file is CONCATENATED after
// prelude.rs and compiled ONCE per (prelude+rt, rustc, target) into a cached rlib
// that Backend-B objects link against. Every symbol here is `extern "C"`.
//
// ABI contract (mirrored by llvmgen.py):
//   SStr    = opaque 24-byte blob, align 8  ([3 x i64] on the LLVM side)
//   RtList  = { data: *mut u8, len: i64, cap: i64 }   (element size supplied per call)
//   SErrC   = { kind: SStr, msg: SStr }
//   status  = i8 (0 ok, 1 error pending — pick the error up with rt_err_take)
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

static mut PENDING: Option<SerpErr> = None;

fn set_pending(e: SerpErr) {
    unsafe { PENDING = Some(e) }
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
    let e = PENDING.take().expect("serp rt: no pending error");
    out.write(SErrC { kind: sstr(&e.kind), msg: sstr(&e.msg) });
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
    let e = PENDING.take().expect("serp rt: no pending error");
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
