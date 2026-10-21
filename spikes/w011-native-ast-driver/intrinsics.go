package hy

// Move performs a zero-cost linear move of an affine variable.
// At compile time, the Go AST analyzer marks the source variable as consumed.
// At runtime, it zeroes the source pointer and returns the value.
func Move[T any](p *T) T {
	v := *p
	var zero T
	*p = zero
	return v
}

// Borrow creates a scoped read-only loan from a container slot or variable.
func Borrow[T any](p *T) *T {
	return p
}

// Task marks a structured concurrent task spawn boundary.
func Task(fn any, args ...any) {
	// Evaluated asynchronously by the Go runtime or scheduler.
}
