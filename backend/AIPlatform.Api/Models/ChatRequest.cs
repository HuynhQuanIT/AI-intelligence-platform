using System.ComponentModel.DataAnnotations;
using System.Text.Json.Serialization;

namespace AIPlatform.Api.Models;

public sealed class ChatRequest
{
    [Required]
    [MinLength(1)]
    [MaxLength(12000)]
    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("use_rag")]
    public bool UseRag { get; set; } = true;

    [JsonPropertyName("model")]
    public string? Model { get; set; }

    [JsonPropertyName("history")]
    public List<HistoryItem> History { get; set; } = new();

    [JsonPropertyName("conversation_id")]
    public string? ConversationId { get; set; }

    // Sinh lại câu trả lời cuối của hội thoại: ai-service xóa lượt hỏi-đáp cuối rồi trả lời lại.
    [JsonPropertyName("regenerate")]
    public bool Regenerate { get; set; }

    // Id tài liệu (đã xử lý) mà người dùng vừa đính kèm trong khung chat.
    [JsonPropertyName("attachment_id")]
    public string? AttachmentId { get; set; }
}

public sealed class HistoryItem
{
    [JsonPropertyName("role")]
    public string Role { get; set; } = "";

    [JsonPropertyName("text")]
    public string Text { get; set; } = "";
}
