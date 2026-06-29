package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"strings"
)

// Config holds iTop connection parameters
type Config struct {
	BaseURL  string
	Username string
	Password string
	Version  string
}

var config *Config

// RestResponse is the standard iTop REST API response
type RestResponse struct {
	Code       int                  `json:"code"`
	Message    string               `json:"message"`
	Objects    map[string]Object    `json:"objects,omitempty"`
	Version    string               `json:"version,omitempty"`
	Operations []Operation          `json:"operations,omitempty"`
	Authorized bool                 `json:"authorized,omitempty"`
	Relations  map[string][]Relation `json:"relations,omitempty"`
}

type Object struct {
	Code    int                    `json:"code"`
	Message string                 `json:"message"`
	Class   string                 `json:"class"`
	Key     interface{}            `json:"key"`
	Fields  map[string]interface{} `json:"fields"`
}

type Operation struct {
	Verb        string `json:"verb"`
	Description string `json:"description"`
	Extension   string `json:"extension"`
}

type Relation struct {
	Key string `json:"key"`
}

// ciSafeFields defines which CI fields are safe to update via MCP
var ciSafeFields = map[string]bool{
	"status": true, "description": true, "serialnumber": true,
	"asset_number": true, "purchase_date": true, "end_of_warranty": true,
}

// ticketSafeFields defines which ticket fields are safe to update via MCP
var ticketSafeFields = map[string]bool{
	"title": true, "description": true, "priority": true,
	"status": true, "solution": true, "pending_reason": true,
}

// validateTicketUpdate checks ticket fields against the safe list
func validateTicketUpdate(fields map[string]interface{}) error {
	for key := range fields {
		if !ticketSafeFields[key] {
			return fmt.Errorf("field '%s' is not in the safe update list for tickets. Allowed: %s", key, ticketSafeFieldsString())
		}
	}
	return nil
}

func ticketSafeFieldsString() string {
	keys := make([]string, 0, len(ticketSafeFields))
	for k := range ticketSafeFields {
		keys = append(keys, k)
	}
	return strings.Join(keys, ", ")
}

// callItopAPI sends a JSON-RPC style request to iTop REST endpoint
func callItopAPI(jsonData string) (*RestResponse, error) {
	var b bytes.Buffer
	w := multipart.NewWriter(&b)

	w.WriteField("version", config.Version)
	w.WriteField("auth_user", config.Username)
	w.WriteField("auth_pwd", config.Password)

	fw, err := w.CreateFormField("json_data")
	if err != nil {
		return nil, fmt.Errorf("failed to create form field: %v", err)
	}
	fw.Write([]byte(jsonData))
	w.Close()

	req, err := http.NewRequest("POST", config.BaseURL, &b)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %v", err)
	}
	req.Header.Set("Content-Type", w.FormDataContentType())

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %v", err)
	}

	var result RestResponse
	err = json.Unmarshal(body, &result)
	if err != nil {
		return nil, fmt.Errorf("failed to parse response: %v\nraw: %s", err, string(body))
	}
	return &result, nil
}

// CheckCredentials verifies iTop credentials
func CheckCredentials(user, password string) (bool, error) {
	jsonData := fmt.Sprintf(`{"operation":"core/check_credentials","user":"%s","password":"%s"}`, user, password)
	resp, err := callItopAPI(jsonData)
	if err != nil {
		return false, err
	}
	if resp.Code != 0 {
		return false, fmt.Errorf("%s", resp.Message)
	}
	return resp.Authorized, nil
}

// ListOperations returns all available iTop operations
func ListOperations() ([]Operation, error) {
	resp, err := callItopAPI(`{"operation":"list_operations"}`)
	if err != nil {
		return nil, err
	}
	if resp.Code != 0 {
		return nil, fmt.Errorf("%s", resp.Message)
	}
	return resp.Operations, nil
}

// GetObjects queries iTop objects (CI or tickets)
func GetObjects(class, key, outputFields string) (map[string]Object, error) {
	jsonData := fmt.Sprintf(`{"operation":"core/get","class":"%s","key":"%s","output_fields":"%s"}`,
		class, key, outputFields)
	resp, err := callItopAPI(jsonData)
	if err != nil {
		return nil, err
	}
	if resp.Code != 0 {
		return nil, fmt.Errorf("%s", resp.Message)
	}
	return resp.Objects, nil
}

// GetRelated returns related objects for a CI
func GetRelated(class string, key int, relation string, depth int, direction string) (*RestResponse, error) {
	jsonData := fmt.Sprintf(`{"operation":"core/get_related","class":"%s","key":%d,"relation":"%s","depth":%d,"direction":"%s"}`,
		class, key, relation, depth, direction)
	resp, err := callItopAPI(jsonData)
	if err != nil {
		return nil, err
	}
	if resp.Code != 0 {
		return nil, fmt.Errorf("%s", resp.Message)
	}
	return resp, nil
}

// CreateObject creates a new iTop object
func CreateObject(class string, fields map[string]interface{}, comment string) (int, error) {
	fieldsJSON, _ := json.Marshal(fields)
	commentJSON := ""
	if comment != "" {
		commentJSON = fmt.Sprintf(`,"comment":"%s"`, comment)
	}
	jsonData := fmt.Sprintf(`{"operation":"core/create","class":"%s"%s,"fields":%s}`,
		class, commentJSON, string(fieldsJSON))
	resp, err := callItopAPI(jsonData)
	if err != nil {
		return 0, err
	}
	if resp.Code != 0 {
		return 0, fmt.Errorf("%s", resp.Message)
	}
	for _, obj := range resp.Objects {
		if v, ok := obj.Key.(float64); ok {
			return int(v), nil
		}
	}
	return 0, nil
}

// UpdateObject updates an existing iTop object
func UpdateObject(class string, key int, fields map[string]interface{}, comment string) error {
	fieldsJSON, _ := json.Marshal(fields)
	commentJSON := ""
	if comment != "" {
		commentJSON = fmt.Sprintf(`,"comment":"%s"`, comment)
	}
	jsonData := fmt.Sprintf(`{"operation":"core/update","class":"%s","key":%d%s,"fields":%s}`,
		class, key, commentJSON, string(fieldsJSON))
	resp, err := callItopAPI(jsonData)
	if err != nil {
		return err
	}
	if resp.Code != 0 {
		return fmt.Errorf("%s", resp.Message)
	}
	return nil
}

// ApplyStimulus applies a state transition
func ApplyStimulus(class string, key int, stimulus string, fields map[string]interface{}) error {
	fieldsJSON := "{}"
	if fields != nil {
		b, _ := json.Marshal(fields)
		fieldsJSON = string(b)
	}
	jsonData := fmt.Sprintf(`{"operation":"core/apply_stimulus","class":"%s","key":%d,"stimulus":"%s","fields":%s}`,
		class, key, stimulus, fieldsJSON)
	resp, err := callItopAPI(jsonData)
	if err != nil {
		return err
	}
	if resp.Code != 0 {
		return fmt.Errorf("%s", resp.Message)
	}
	return nil
}

// validateCIUpdate checks fields against the safe list
func validateCIUpdate(fields map[string]interface{}) error {
	for key := range fields {
		if !ciSafeFields[key] {
			return fmt.Errorf("field '%s' is not in the safe update list. Allowed: %s", key, safeFieldsString())
		}
	}
	return nil
}

func safeFieldsString() string {
	keys := make([]string, 0, len(ciSafeFields))
	for k := range ciSafeFields {
		keys = append(keys, k)
	}
	return strings.Join(keys, ", ")
}
