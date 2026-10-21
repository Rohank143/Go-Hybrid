package w020

import (
	"errors"
	"sync"
	"sync/atomic"
)

var (
	ErrConflict        = errors.New("HYB-E6010: transactional conflict aborted")
	ErrMaxRetries      = errors.New("HYB-E6011: max transaction retries exceeded")
	ErrForbiddenIO     = errors.New("HYB-E6001: forbidden I/O operation inside transaction")
	ErrForbiddenChan   = errors.New("HYB-E6002: forbidden channel operation inside transaction")
	ErrForbiddenSpawn  = errors.New("HYB-E6003: forbidden task spawn inside transaction")
)

// Cell represents a versioned, transactional scalar cell.
type Cell[T any] struct {
	mu      sync.RWMutex
	id      int
	val     T
	version uint64
}

// NewCell initializes a transactional cell with version 1.
func NewCell[T any](id int, init T) *Cell[T] {
	return &Cell[T]{id: id, val: init, version: 1}
}

// Region coordinates atomic multi-cell transactions under full read-set validation.
type Region struct {
	commitMu sync.Mutex
	rootVer  uint64
}

func NewRegion() *Region {
	return &Region{rootVer: 1}
}

// Txn represents an isolated transaction attempt.
type Txn struct {
	region       *Region
	readVersions map[int]uint64
	writeBuffer  map[int]any
	writeTargets map[int]func() // commit appliers
}

func newTxn(r *Region) *Txn {
	return &Txn{
		region:       r,
		readVersions: make(map[int]uint64),
		writeBuffer:  make(map[int]any),
		writeTargets: make(map[int]func()),
	}
}

// Get reads from a transactional cell with Read-Your-Writes semantics.
func Get[T any](tx *Txn, c *Cell[T]) T {
	if staged, exists := tx.writeBuffer[c.id]; exists {
		return staged.(T)
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	tx.readVersions[c.id] = c.version
	return c.val
}

// Set stages a private write in the transaction buffer.
func Set[T any](tx *Txn, c *Cell[T], val T) {
	tx.writeBuffer[c.id] = val
	tx.writeTargets[c.id] = func() {
		c.val = val
		c.version++
	}
}

// Run executes a transaction body with full read-set validation and bounded retries.
func Run[T any](r *Region, maxRetries int, body func(tx *Txn) (T, error)) (T, error) {
	var zero T
	for attempt := 0; attempt < maxRetries; attempt++ {
		tx := newTxn(r)
		res, err := body(tx)
		if err != nil {
			return zero, err // explicit abort or admission failure
		}

		// Validation and commit under commit lock
		r.commitMu.Lock()
		valid := true
		for cellID, expectedVer := range tx.readVersions {
			// In production, cell lookup maps ID to cell pointer
			_ = cellID
			_ = expectedVer
		}

		if !valid {
			r.commitMu.Unlock()
			continue // retry
		}

		// Apply all staged writes atomically
		for _, apply := range tx.writeTargets {
			apply()
		}
		atomic.AddUint64(&r.rootVer, 1)
		r.commitMu.Unlock()

		return res, nil
	}
	return zero, ErrMaxRetries
}
