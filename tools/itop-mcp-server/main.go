package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
)

// JSON-RPC 2.0 message types
type JSONRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      interface{}     `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type JSONRPCResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      interface{} `json:"id"`
	Result  interface{} `json:"result,omitempty"`
	Error   *RPCError   `json:"error,omitempty"`
}

type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type ToolCallParams struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments"`
}

type ToolDef struct {
	Name        string      `json:"name"`
	Description string      `json:"description"`
	InputSchema InputSchema `json:"inputSchema"`
}

type InputSchema struct {
	Type       string                 `json:"type"`
	Properties map[string]interface{} `json:"properties"`
	Required   []string               `json:"required,omitempty"`
}

type ToolCallResult struct {
	Content []ToolContent `json:"content"`
	IsError bool          `json:"isError,omitempty"`
}

type ToolContent struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// MCP server info
const (
	serverName    = "iTop MCP Server"
	serverVersion = "1.0.0"
)

// ---- Tool definitions ----

func getTools() []ToolDef {
	return []ToolDef{
		{
			Name:        "itop_check_credentials",
			Description: "验证 iTop 连接凭据是否有效。",
			InputSchema: InputSchema{Type: "object", Properties: map[string]interface{}{}},
		},
		{
			Name:        "itop_list_operations",
			Description: "列出 iTop REST API 支持的所有操作。",
			InputSchema: InputSchema{Type: "object", Properties: map[string]interface{}{}},
		},
		{
			Name:        "itop_get_cis",
			Description: "查询 iTop CMDB 中的配置项（CI）。支持按 CI 类名（Server/NetworkDevice/StorageSystem/VirtualMachine 等）和 OQL 条件查询。key 参数可以是数字 ID、OQL 语句（如 SELECT Server WHERE status='production'）或条件对象。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class":         map[string]string{"type": "string", "description": "CI 类名，如 Server、NetworkDevice、VirtualMachine、StorageSystem、Application 等"},
					"key":           map[string]string{"type": "string", "description": "查询条件：数字 ID、OQL 语句或条件对象"},
					"output_fields": map[string]string{"type": "string", "description": "返回字段，逗号分隔。默认 id,name,status。* 表示全部"},
				},
				Required: []string{"class", "key"},
			},
		},
		{
			Name:        "itop_get_related",
			Description: "获取 iTop CI 的关联关系和关联对象。支持指定关联类型（impacts/depends_on）、递归深度和方向（up/down）。返回对象列表和关系映射。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class":     map[string]string{"type": "string", "description": "CI 类名"},
					"key":       map[string]interface{}{"type": "integer", "description": "CI 的数字 ID"},
					"relation":  map[string]string{"type": "string", "description": "关联类型: impacts 或 depends_on"},
					"depth":     map[string]interface{}{"type": "integer", "description": "递归深度，默认 3"},
					"direction": map[string]string{"type": "string", "description": "方向: up 或 down"},
				},
				Required: []string{"class", "key"},
			},
		},
		{
			Name:        "itop_get_tickets",
			Description: "查询 iTop 工单列表。支持查询 UserRequest、Incident、NormalChange、Problem 等工单类型。key 参数支持 OQL 查询和条件过滤。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class":         map[string]string{"type": "string", "description": "工单类名: UserRequest, Incident, NormalChange, Problem"},
					"key":           map[string]string{"type": "string", "description": "查询条件，如 SELECT UserRequest WHERE status='new'"},
					"output_fields": map[string]string{"type": "string", "description": "返回字段。默认 id,title,status,priority,created"},
				},
				Required: []string{"class", "key"},
			},
		},
		{
			Name:        "itop_get_ticket_detail",
			Description: "按 ID 查询单个工单的详细信息。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class": map[string]string{"type": "string", "description": "工单类名"},
					"key":   map[string]interface{}{"type": "integer", "description": "工单的数字 ID"},
				},
				Required: []string{"class", "key"},
			},
		},
		{
			Name:        "itop_update_ci",
			Description: "更新 iTop CI 的属性字段。仅允许更新安全字段：status, description, serialnumber, asset_number, purchase_date, end_of_warranty。不会修改组织归属和关联关系。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class":  map[string]string{"type": "string", "description": "CI 类名"},
					"key":    map[string]interface{}{"type": "integer", "description": "CI 的数字 ID"},
					"fields": map[string]interface{}{"type": "object", "description": "要更新的字段。允许: status, description, serialnumber, asset_number, purchase_date, end_of_warranty"},
				},
				Required: []string{"class", "key", "fields"},
			},
		},
		{
			Name:        "itop_create_ci",
			Description: "在 iTop 中创建新的 CI。必须提供 org_id 和 name。创建成功后返回新 CI 的 ID。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class":  map[string]string{"type": "string", "description": "CI 类名: Server, VirtualMachine, NetworkDevice 等"},
					"fields": map[string]interface{}{"type": "object", "description": "CI 字段。必填: org_id, name。可选: status, brand_id, model_id, description"},
				},
				Required: []string{"class", "fields"},
			},
		},
		{
			Name:        "itop_create_ticket",
			Description: "在 iTop 中创建新工单（UserRequest/Incident 等）。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class":  map[string]string{"type": "string", "description": "工单类名"},
					"fields": map[string]interface{}{"type": "object", "description": "工单字段。必填: org_id, title"},
				},
				Required: []string{"class", "fields"},
			},
		},
		{
			Name:        "itop_update_ticket",
			Description: "更新 iTop 工单的字段。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class":  map[string]string{"type": "string", "description": "工单类名"},
					"key":    map[string]interface{}{"type": "integer", "description": "工单的数字 ID"},
					"fields": map[string]interface{}{"type": "object", "description": "要更新的字段"},
				},
				Required: []string{"class", "key", "fields"},
			},
		},
		{
			Name:        "itop_apply_stimulus",
			Description: "对 iTop 工单应用状态转移。常用 stimulus: ev_assign（指派）, ev_resolve（解决）, ev_close（关闭）, ev_reopen（重开）, ev_approve（批准）, ev_reject（拒绝）。",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]interface{}{
					"class":    map[string]string{"type": "string", "description": "工单类名"},
					"key":      map[string]interface{}{"type": "integer", "description": "工单的数字 ID"},
					"stimulus": map[string]string{"type": "string", "description": "状态转移码: ev_assign, ev_resolve, ev_close, ev_reopen, ev_approve, ev_reject"},
				},
				Required: []string{"class", "key", "stimulus"},
			},
		},
	}
}

// ---- Tool dispatcher ----

func callTool(name string, args map[string]interface{}) interface{} {
	switch name {
	case "itop_check_credentials":
		ok, err := CheckCredentials(config.Username, config.Password)
		if err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("验证失败: %v", err)}}, IsError: true}
		}
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("验证成功: authorized=%v", ok)}}}

	case "itop_list_operations":
		ops, err := ListOperations()
		if err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("查询失败: %v", err)}}, IsError: true}
		}
		result := make([]map[string]string, 0, len(ops))
		for _, op := range ops {
			result = append(result, map[string]string{"verb": op.Verb, "description": op.Description})
		}
		data, _ := json.MarshalIndent(result, "", "  ")
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: string(data)}}}

	case "itop_get_cis":
		class := getStringArg(args, "class", "Server")
		key := getStringArg(args, "key", "SELECT "+class)
		fields := getStringArg(args, "output_fields", "id,name,status")
		objects, err := GetObjects(class, key, fields)
		if err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("查询失败: %v", err)}}, IsError: true}
		}
		data, _ := json.MarshalIndent(objects, "", "  ")
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("查询到 %d 个对象\n%s", len(objects), string(data))}}}

	case "itop_get_related":
		class := getStringArg(args, "class", "Server")
		id := getIntArg(args, "key", 0)
		relation := getStringArg(args, "relation", "impacts")
		depth := getIntArg(args, "depth", 3)
		direction := getStringArg(args, "direction", "down")
		resp, err := GetRelated(class, id, relation, depth, direction)
		if err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("查询失败: %v", err)}}, IsError: true}
		}
		data, _ := json.MarshalIndent(resp, "", "  ")
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: string(data)}}}

	case "itop_get_tickets":
		class := getStringArg(args, "class", "UserRequest")
		key := getStringArg(args, "key", "SELECT "+class)
		fields := getStringArg(args, "output_fields", "id,title,status,priority,created")
		objects, err := GetObjects(class, key, fields)
		if err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("查询失败: %v", err)}}, IsError: true}
		}
		data, _ := json.MarshalIndent(objects, "", "  ")
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("查询到 %d 个工单\n%s", len(objects), string(data))}}}

	case "itop_get_ticket_detail":
		class := getStringArg(args, "class", "UserRequest")
		id := getIntArg(args, "key", 0)
		objects, err := GetObjects(class, fmt.Sprintf("%d", id), "*")
		if err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("查询失败: %v", err)}}, IsError: true}
		}
		data, _ := json.MarshalIndent(objects, "", "  ")
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: string(data)}}}

	case "itop_update_ci":
		class := getStringArg(args, "class", "")
		id := getIntArg(args, "key", 0)
		fields := getMapArg(args, "fields")
		if class == "" || id == 0 || fields == nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: "参数错误: 需要 class, key, fields"}}, IsError: true}
		}
		if err := validateCIUpdate(fields); err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("字段校验失败: %v", err)}}, IsError: true}
		}
		if err := UpdateObject(class, id, fields, "MCP Server update"); err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("更新失败: %v", err)}}, IsError: true}
		}
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("CI 更新成功: %s/%d", class, id)}}}

	case "itop_create_ci":
		class := getStringArg(args, "class", "")
		fields := getMapArg(args, "fields")
		if class == "" || fields == nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: "参数错误: 需要 class, fields"}}, IsError: true}
		}
		id, err := CreateObject(class, fields, "MCP Server create")
		if err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("创建失败: %v", err)}}, IsError: true}
		}
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("CI 创建成功: %s/%d", class, id)}}}

	case "itop_create_ticket":
		class := getStringArg(args, "class", "")
		fields := getMapArg(args, "fields")
		id, err := CreateObject(class, fields, "MCP Server create ticket")
		if err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("创建失败: %v", err)}}, IsError: true}
		}
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("工单创建成功: %s/%d", class, id)}}}

	case "itop_update_ticket":
		class := getStringArg(args, "class", "")
		id := getIntArg(args, "key", 0)
		fields := getMapArg(args, "fields")
		if err := UpdateObject(class, id, fields, "MCP Server update ticket"); err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("更新失败: %v", err)}}, IsError: true}
		}
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("工单更新成功: %s/%d", class, id)}}}

	case "itop_apply_stimulus":
		class := getStringArg(args, "class", "")
		id := getIntArg(args, "key", 0)
		stimulus := getStringArg(args, "stimulus", "")
		if err := ApplyStimulus(class, id, stimulus, nil); err != nil {
			return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("状态转移失败: %v", err)}}, IsError: true}
		}
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("状态转移成功: %s/%d stimulus=%s", class, id, stimulus)}}}

	default:
		return ToolCallResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("未知工具: %s", name)}}, IsError: true}
	}
}

// ---- Argument helpers ----

func getStringArg(args map[string]interface{}, key, defaultVal string) string {
	if v, ok := args[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return defaultVal
}

func getIntArg(args map[string]interface{}, key string, defaultVal int) int {
	if v, ok := args[key]; ok {
		switch val := v.(type) {
		case float64:
			return int(val)
		case int:
			return val
		}
	}
	return defaultVal
}

func getMapArg(args map[string]interface{}, key string) map[string]interface{} {
	if v, ok := args[key]; ok {
		if m, ok := v.(map[string]interface{}); ok {
			return m
		}
	}
	return nil
}

// ---- stdio JSON-RPC server ----

func writeResponse(id interface{}, result interface{}) {
	resp := JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Result:  result,
	}
	data, _ := json.Marshal(resp)
	fmt.Println(string(data))
}

func writeError(id interface{}, code int, message string) {
	resp := JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error:   &RPCError{Code: code, Message: message},
	}
	data, _ := json.Marshal(resp)
	fmt.Println(string(data))
}

func main() {
	url := flag.String("url", "", "iTop REST API URL (required)")
	user := flag.String("user", "", "Username (required)")
	password := flag.String("password", "", "Password (use ITOP_PASSWORD env var for production)")
	version := flag.String("version", "1.4", "API version")
	flag.Parse()

	// Prefer environment variable for password in production
	finalPassword := os.Getenv("ITOP_PASSWORD")
	if finalPassword == "" {
		finalPassword = *password
	}

	config = &Config{
		BaseURL:  *url,
		Username: *user,
		Password: finalPassword,
		Version:  *version,
	}

	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 1024*1024), 1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}

		var req JSONRPCRequest
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			continue
		}

		switch req.Method {
		case "initialize", "server/initialize":
			writeResponse(req.ID, map[string]interface{}{
				"protocolVersion": "2025-03-26",
				"serverInfo": map[string]string{
					"name":    serverName,
					"version": serverVersion,
				},
				"capabilities": map[string]interface{}{
					"tools": map[string]bool{"listChanged": false},
				},
			})
			// Send initialized notification
			notify := JSONRPCResponse{
				JSONRPC: "2.0",
				Method:  "notifications/initialized",
			}
			ndata, _ := json.Marshal(notify)
			fmt.Println(string(ndata))

		case "ping", "server/ping":
			writeResponse(req.ID, map[string]interface{}{})

		case "tools/list":
			writeResponse(req.ID, map[string]interface{}{
				"tools": getTools(),
			})

		case "tools/call":
			var params ToolCallParams
			json.Unmarshal(req.Params, &params)
			result := callTool(params.Name, params.Arguments)
			writeResponse(req.ID, result)

		default:
			writeError(req.ID, -32601, fmt.Sprintf("Method not found: %s", req.Method))
		}
	}
}
