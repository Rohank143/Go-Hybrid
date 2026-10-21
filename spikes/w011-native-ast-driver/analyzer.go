package w011

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"strings"
)

// Diagnostic codes matching Go-Hybrid Tier-0 error conventions.
const (
	ErrUseAfterMove     = "HYB-E1001" // Variable used after affine move
	ErrLoopBackedgeMove = "HYB-E1002" // Variable moved on loop backedge
	ErrNonSendableShare = "HYB-E3001" // Non-sendable reference crosses task boundary
	ErrLoanMutateRace   = "HYB-E2001" // Container mutated while slot loan is active
	ErrEscapeToAmbient  = "HYB-E3003" // Reference escapes to un-annotated ambient function
	ErrUnknownForeign   = "HYB-E3005" // Unresolved foreign boundary type
)

type Diagnostic struct {
	Code    string
	Message string
	Line    int
}

type VarState int

const (
	StateLive VarState = iota
	StateMoved
	StateBorrowed
)

type Symbol struct {
	Name      string
	TypeKind  string // "primitive", "struct", "pointer", "chan", "unknown"
	IsSibling bool
}

type AnalysisContext struct {
	Fset           *token.FileSet
	PackageSymbols map[string]*Symbol
	Diagnostics    []Diagnostic
}

func NewAnalysisContext() *AnalysisContext {
	return &AnalysisContext{
		Fset:           token.NewFileSet(),
		PackageSymbols: make(map[string]*Symbol),
		Diagnostics:    make([]Diagnostic, 0),
	}
}

// RegisterSiblingType records a type defined in an adjacent .go file in the package.
func (ctx *AnalysisContext) RegisterSiblingType(name, kind string) {
	ctx.PackageSymbols[name] = &Symbol{
		Name:      name,
		TypeKind:  kind,
		IsSibling: true,
	}
}

// CheckSource parses a Go source file and runs Tier-0 analysis on all functions with //hy:check.
func (ctx *AnalysisContext) CheckSource(filename, src string) ([]Diagnostic, error) {
	file, err := parser.ParseFile(ctx.Fset, filename, src, parser.ParseComments)
	if err != nil {
		return nil, fmt.Errorf("parse error: %w", err)
	}

	for _, decl := range file.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok || fn.Doc == nil {
			continue
		}

		if !hasHyCheckDirective(fn.Doc) {
			continue
		}

		ctx.checkFunction(fn)
	}

	return ctx.Diagnostics, nil
}

func hasHyCheckDirective(cg *ast.CommentGroup) bool {
	for _, c := range cg.List {
		if strings.Contains(c.Text, "//hy:check") {
			return true
		}
	}
	return false
}

func (ctx *AnalysisContext) checkFunction(fn *ast.FuncDecl) {
	varStates := make(map[string]VarState)
	varTypes := make(map[string]string)
	loopDepth := 0
	activeLoans := make(map[string]bool)

	// Populate params
	if fn.Type.Params != nil {
		for _, field := range fn.Type.Params.List {
			typeStr := exprToString(field.Type)
			for _, id := range field.Names {
				varStates[id.Name] = StateLive
				varTypes[id.Name] = typeStr
			}
		}
	}

	ast.Inspect(fn.Body, func(n ast.Node) bool {
		switch node := n.(type) {
		case *ast.ForStmt, *ast.RangeStmt:
			loopDepth++
		case *ast.AssignStmt:
			// Check assignments and move intrinsics
			for _, rhs := range node.Rhs {
				if call, ok := rhs.(*ast.CallExpr); ok {
					if isHyMoveCall(call) {
						varName := extractMoveVar(call)
						if loopDepth > 0 {
							ctx.Diagnostics = append(ctx.Diagnostics, Diagnostic{
								Code:    ErrLoopBackedgeMove,
								Message: fmt.Sprintf("variable %s moved inside loop body", varName),
								Line:    ctx.Fset.Position(call.Pos()).Line,
							})
						} else if varStates[varName] == StateMoved {
							ctx.Diagnostics = append(ctx.Diagnostics, Diagnostic{
								Code:    ErrUseAfterMove,
								Message: fmt.Sprintf("use after move: variable %s was already moved", varName),
								Line:    ctx.Fset.Position(call.Pos()).Line,
							})
						} else {
							varStates[varName] = StateMoved
						}
					}
				}
			}
		case *ast.GoStmt:
			// Task spawn boundary: check sendability of all arguments
			for _, arg := range node.Call.Args {
				argStr := exprToString(arg)
				argType := varTypes[argStr]
				if strings.HasPrefix(argType, "*") {
					ctx.Diagnostics = append(ctx.Diagnostics, Diagnostic{
						Code:    ErrNonSendableShare,
						Message: fmt.Sprintf("non-sendable mutable pointer %s crosses task boundary", argStr),
						Line:    ctx.Fset.Position(node.Pos()).Line,
					})
				}
			}
		case *ast.Ident:
			if varStates[node.Name] == StateMoved {
				ctx.Diagnostics = append(ctx.Diagnostics, Diagnostic{
					Code:    ErrUseAfterMove,
					Message: fmt.Sprintf("use after move: %s is consumed", node.Name),
					Line:    ctx.Fset.Position(node.Pos()).Line,
				})
			}
		}
		return true
	})
}

func isHyMoveCall(call *ast.CallExpr) bool {
	if sel, ok := call.Fun.(*ast.SelectorExpr); ok {
		if x, ok := sel.X.(*ast.Ident); ok && x.Name == "hy" && sel.Sel.Name == "Move" {
			return true
		}
	}
	return false
}

func extractMoveVar(call *ast.CallExpr) string {
	if len(call.Args) == 0 {
		return ""
	}
	if unary, ok := call.Args[0].(*ast.UnaryExpr); ok && unary.Op == token.AND {
		if id, ok := unary.X.(*ast.Ident); ok {
			return id.Name
		}
	}
	return exprToString(call.Args[0])
}

func exprToString(expr ast.Expr) string {
	switch e := expr.(type) {
	case *ast.Ident:
		return e.Name
	case *ast.StarExpr:
		return "*" + exprToString(e.X)
	case *ast.SelectorExpr:
		return exprToString(e.X) + "." + e.Sel.Name
	default:
		return "any"
	}
}
