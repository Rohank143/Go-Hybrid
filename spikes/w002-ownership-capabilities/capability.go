package w002

// CapabilityKind represents the type-carried ownership permission.
type CapabilityKind int

const (
	CapPrimitive CapabilityKind = iota
	CapOwn                      // Exclusive linear ownership
	CapShare                    // Immutable, freely duplicable share
	CapBorrow                   // Scoped read/write loan
)

// Capability tracks the permission carried directly by a type.
type Capability struct {
	Kind     CapabilityKind
	TypeName string
	IsAffine bool
}

// Own creates an exclusive linear capability.
func Own(typeName string) Capability {
	return Capability{Kind: CapOwn, TypeName: typeName, IsAffine: true}
}

// Share creates an immutable shared capability.
func Share(typeName string) Capability {
	return Capability{Kind: CapShare, TypeName: typeName, IsAffine: false}
}

// Borrow creates a scoped loan capability.
func Borrow(typeName string) Capability {
	return Capability{Kind: CapBorrow, TypeName: typeName, IsAffine: false}
}
