using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.ComponentModel.DataAnnotations;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

builder.Services.AddHttpClient("ai", c =>
{
    c.BaseAddress = new Uri(
        builder.Configuration["AiService:BaseUrl"] ?? "http://localhost:8000");
    c.Timeout = TimeSpan.FromSeconds(90);
});

builder.Services.AddCors(o =>
    o.AddDefaultPolicy(p =>
        p.WithOrigins("http://localhost:5173")
         .AllowAnyHeader()
         .AllowAnyMethod()));

var app = builder.Build();

app.UseCors();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.MapGet("/health", () =>
    Results.Ok(new { status = "healthy", service = "backend" }));

app.MapGet("/api/platform/health",
    async (IHttpClientFactory f) => await Get(f, "/health"));

app.MapPost("/api/platform/chat",
    async (ChatRequest body, IHttpClientFactory f) =>
    {
        var json = JsonSerializer.Serialize(body);

        var response = await f.CreateClient("ai").PostAsync(
            "/chat",
            new StringContent(json, Encoding.UTF8, "application/json"));

        return Results.Content(
            await response.Content.ReadAsStringAsync(),
            "application/json",
            statusCode: (int)response.StatusCode);
    })
    .Accepts<ChatRequest>("application/json");

app.MapPost("/api/platform/chat/stream",
    async (ChatRequest body, HttpContext ctx, IHttpClientFactory f) =>
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "/chat/stream")
        {
            Content = new StringContent(
                JsonSerializer.Serialize(body), Encoding.UTF8, "application/json")
        };

        // ResponseHeadersRead: nhận header ngay, rồi chuyển tiếp từng đoạn khi ai-service gửi.
        using var response = await f.CreateClient("ai").SendAsync(
            request, HttpCompletionOption.ResponseHeadersRead, ctx.RequestAborted);

        ctx.Response.StatusCode = (int)response.StatusCode;
        ctx.Response.ContentType = response.IsSuccessStatusCode
            ? "text/event-stream"
            : "application/json";
        ctx.Response.Headers["Cache-Control"] = "no-cache";
        ctx.Response.Headers["X-Accel-Buffering"] = "no";

        try
        {
            await using var stream = await response.Content.ReadAsStreamAsync(ctx.RequestAborted);
            var buffer = new byte[4096];
            int read;
            while ((read = await stream.ReadAsync(buffer.AsMemory(), ctx.RequestAborted)) > 0)
            {
                await ctx.Response.Body.WriteAsync(buffer.AsMemory(0, read), ctx.RequestAborted);
                await ctx.Response.Body.FlushAsync(ctx.RequestAborted);
            }
        }
        catch (OperationCanceledException)
        {
            // Trình duyệt đóng kết nối giữa chừng: không phải lỗi.
        }
    })
    .Accepts<ChatRequest>("application/json");

app.MapGet("/api/platform/conversations",
    async (IHttpClientFactory f) => await Get(f, "/conversations"));

app.MapPost("/api/platform/conversations",
    async (IHttpClientFactory f) =>
    {
        var response = await f.CreateClient("ai").PostAsync("/conversations", null);

        return Results.Content(
            await response.Content.ReadAsStringAsync(),
            "application/json",
            statusCode: (int)response.StatusCode);
    });

app.MapGet("/api/platform/conversations/{conversationId}/messages",
    async (string conversationId, IHttpClientFactory f) =>
        await Get(f, $"/conversations/{Uri.EscapeDataString(conversationId)}/messages"));

app.MapDelete("/api/platform/conversations/{conversationId}",
    async (string conversationId, IHttpClientFactory f) =>
    {
        var response = await f.CreateClient("ai").DeleteAsync(
            $"/conversations/{Uri.EscapeDataString(conversationId)}");

        return Results.Content(
            await response.Content.ReadAsStringAsync(),
            "application/json",
            statusCode: (int)response.StatusCode);
    });

app.MapPost("/api/platform/documents",
    async (HttpRequest r, IHttpClientFactory f) =>
        await Post(r, f, "/documents"));

app.MapPost("/api/platform/documents/upload",
    async (HttpRequest r, IHttpClientFactory f) =>
    {
        const long maxBytes = 11 * 1024 * 1024; // 10 MB file + phần đệm multipart

        if (!r.HasFormContentType || string.IsNullOrEmpty(r.ContentType))
        {
            return Results.Json(
                new { detail = "Expected multipart/form-data." },
                statusCode: StatusCodes.Status415UnsupportedMediaType);
        }

        if (r.ContentLength is > maxBytes)
        {
            return Results.Json(
                new { detail = "File vượt quá 10 MB." },
                statusCode: StatusCodes.Status413PayloadTooLarge);
        }

        // Chuyển nguyên multipart sang ai-service, không parse ở gateway.
        using var buffer = new MemoryStream();
        await r.Body.CopyToAsync(buffer);
        if (buffer.Length > maxBytes)
        {
            return Results.Json(
                new { detail = "File vượt quá 10 MB." },
                statusCode: StatusCodes.Status413PayloadTooLarge);
        }
        buffer.Position = 0;

        using var content = new StreamContent(buffer);
        content.Headers.ContentType = MediaTypeHeaderValue.Parse(r.ContentType);

        var response = await f.CreateClient("ai").PostAsync(
            "/documents/upload", content);

        return Results.Content(
            await response.Content.ReadAsStringAsync(),
            "application/json",
            statusCode: (int)response.StatusCode);
    });

app.MapGet("/api/platform/documents",
    async (IHttpClientFactory f) => await Get(f, "/documents"));

app.MapGet("/api/platform/documents/{documentId}",
    async (string documentId, IHttpClientFactory f) =>
        await Get(f, $"/documents/{Uri.EscapeDataString(documentId)}"));

app.MapDelete("/api/platform/documents/{documentId}",
    async (string documentId, IHttpClientFactory f) =>
    {
        var response = await f.CreateClient("ai").DeleteAsync(
            $"/documents/{Uri.EscapeDataString(documentId)}");

        return Results.Content(
            await response.Content.ReadAsStringAsync(),
            "application/json",
            statusCode: (int)response.StatusCode);
    });

app.MapGet("/api/platform/documents/{documentId}/file",
    async (string documentId, HttpContext ctx, IHttpClientFactory f) =>
    {
        var response = await f.CreateClient("ai").GetAsync(
            $"/documents/{Uri.EscapeDataString(documentId)}/file");

        if (!response.IsSuccessStatusCode)
        {
            return Results.Content(
                await response.Content.ReadAsStringAsync(),
                "application/json",
                statusCode: (int)response.StatusCode);
        }

        var name = "document";
        if (response.Headers.TryGetValues("X-Document-Filename", out var values))
        {
            name = Uri.UnescapeDataString(values.First());
        }

        var contentType = response.Content.Headers.ContentType?.ToString()
            ?? "application/octet-stream";

        ctx.Response.Headers["X-Content-Type-Options"] = "nosniff";

        return Results.File(
            await response.Content.ReadAsByteArrayAsync(),
            contentType,
            name);
    });

app.MapGet("/api/platform/agents",
    async (IHttpClientFactory f) => await Get(f, "/agents"));

app.MapGet("/api/platform/metrics",
    async (IHttpClientFactory f) => await Get(f, "/metrics"));

app.MapGet("/api/platform/traces",
    async (IHttpClientFactory f) => await Get(f, "/traces"));

app.MapPost("/api/platform/evaluate",
    async (HttpRequest r, IHttpClientFactory f) =>
        await Post(r, f, "/evaluate"));

app.MapPost("/api/platform/security/scan",
    async (HttpRequest r, IHttpClientFactory f) =>
        await Post(r, f, "/security/scan"));

app.MapGet("/api/platform/security/events",
    async (IHttpClientFactory f) => await Get(f, "/security/events"));

app.Run();

static async Task<IResult> Get(IHttpClientFactory f, string path)
{
    var response = await f.CreateClient("ai").GetAsync(path);

    return Results.Content(
        await response.Content.ReadAsStringAsync(),
        "application/json",
        statusCode: (int)response.StatusCode);
}

static async Task<IResult> Post(
    HttpRequest req,
    IHttpClientFactory f,
    string path)
{
    using var reader = new StreamReader(req.Body);
    var body = await reader.ReadToEndAsync();

    var response = await f.CreateClient("ai").PostAsync(
        path,
        new StringContent(body, Encoding.UTF8, "application/json"));

    return Results.Content(
        await response.Content.ReadAsStringAsync(),
        "application/json",
        statusCode: (int)response.StatusCode);
}

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
}

public sealed class HistoryItem
{
    [JsonPropertyName("role")]
    public string Role { get; set; } = "";

    [JsonPropertyName("text")]
    public string Text { get; set; } = "";
}