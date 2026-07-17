// Handwritten-Rust reference for bench_alloc.py.
struct Particle { _x: f64, _y: f64, vx: f64, vy: f64 }

impl Particle {
    fn energy(&self) -> f64 { 0.5 * (self.vx * self.vx + self.vy * self.vy) }
}

fn step(n: i64) -> f64 {
    let mut total = 0.0;
    for i in 0..n {
        let mut xs: Vec<i64> = Vec::new();
        for j in 0..20 {
            xs.push(i + j);
        }
        let p = Particle { _x: 1.0, _y: 2.0, vx: (i % 7) as f64, vy: (i % 11) as f64 };
        total += p.energy() + xs.len() as f64;
    }
    total
}

fn main() {
    println!("{}", step(300000));
}
