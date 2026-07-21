export class SerialQueue {
  constructor() {
    this.tail = Promise.resolve();
    this.depth = 0;
  }

  enqueue(fn) {
    this.depth += 1;
    const run = this.tail.then(fn, fn);
    this.tail = run.catch(() => {});
    return run.finally(() => {
      this.depth -= 1;
    });
  }
}

export class LimitQueue {
  constructor(limit) {
    if (!Number.isInteger(limit) || limit < 1) throw new Error('invalid_queue_limit');
    this.limit = limit;
    this.active = 0;
    this.pending = [];
  }

  enqueue(fn) {
    return new Promise((resolve, reject) => {
      this.pending.push({ fn, resolve, reject });
      this.pump();
    });
  }

  pump() {
    while (this.active < this.limit && this.pending.length) {
      const item = this.pending.shift();
      this.active += 1;
      Promise.resolve()
        .then(item.fn)
        .then(item.resolve, item.reject)
        .finally(() => {
          this.active -= 1;
          this.pump();
        });
    }
  }

  get depth() {
    return this.pending.length + this.active;
  }
}
