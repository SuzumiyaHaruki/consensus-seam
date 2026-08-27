package main

import (
	"encoding/json"
	"flag"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
)

type result struct {
	Kind     string `json:"kind"`
	Receiver string `json:"receiver,omitempty"`
	Name     string `json:"name"`
	File     string `json:"file"`
	Line     int    `json:"line"`
}

func receiverName(expr ast.Expr) string {
	switch value := expr.(type) {
	case *ast.Ident:
		return value.Name
	case *ast.StarExpr:
		return receiverName(value.X)
	case *ast.IndexExpr:
		return receiverName(value.X)
	case *ast.IndexListExpr:
		return receiverName(value.X)
	case *ast.SelectorExpr:
		return value.Sel.Name
	default:
		return ""
	}
}

func main() {
	root := flag.String("root", ".", "Go source root")
	kind := flag.String("kind", "type", "type or method")
	receiver := flag.String("receiver", "", "method receiver")
	name := flag.String("name", "", "type or method name")
	flag.Parse()

	fset := token.NewFileSet()
	results := []result{}
	err := filepath.WalkDir(*root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			if path != *root && (entry.Name() == ".git" || entry.Name() == "vendor") {
				return filepath.SkipDir
			}
			return nil
		}
		if filepath.Ext(path) != ".go" {
			return nil
		}
		file, parseErr := parser.ParseFile(fset, path, nil, 0)
		if parseErr != nil {
			return nil
		}
		relative, relErr := filepath.Rel(*root, path)
		if relErr != nil {
			return relErr
		}
		for _, declaration := range file.Decls {
			switch value := declaration.(type) {
			case *ast.GenDecl:
				if *kind != "type" || value.Tok != token.TYPE {
					continue
				}
				for _, specification := range value.Specs {
					typeSpec, ok := specification.(*ast.TypeSpec)
					if ok && typeSpec.Name.Name == *name {
						position := fset.Position(typeSpec.Pos())
						results = append(results, result{Kind: "type", Name: *name, File: filepath.ToSlash(relative), Line: position.Line})
					}
				}
			case *ast.FuncDecl:
				if *kind != "method" || value.Recv == nil || value.Name.Name != *name || len(value.Recv.List) == 0 {
					continue
				}
				receiverValue := receiverName(value.Recv.List[0].Type)
				if receiverValue == *receiver {
					position := fset.Position(value.Pos())
					results = append(results, result{Kind: "method", Receiver: receiverValue, Name: *name, File: filepath.ToSlash(relative), Line: position.Line})
				}
			}
		}
		return nil
	})
	if err != nil {
		_, _ = os.Stderr.WriteString(err.Error())
		os.Exit(1)
	}
	sort.Slice(results, func(i, j int) bool {
		if results[i].File == results[j].File {
			return results[i].Line < results[j].Line
		}
		return results[i].File < results[j].File
	})
	if encodeErr := json.NewEncoder(os.Stdout).Encode(results); encodeErr != nil {
		os.Exit(1)
	}
}
