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

app.MapPost("/api/platform/documents",
    async (HttpRequest r, IHttpClientFactory f) =>
        await Post(r, f, "/documents"));

app.MapGet("/api/platform/documents",
    async (IHttpClientFactory f) => await Get(f, "/documents"));

app.MapGet("/api/platform/documents/{documentId}",
    async (string documentId, IHttpClientFactory f) =>
        await Get(f, $"/documents/{Uri.EscapeDataString(documentId)}"));

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
}

public sealed class HistoryItem
{
    [JsonPropertyName("role")]
    public string Role { get; set; } = "";

    [JsonPropertyName("text")]
    public string Text { get; set; } = "";
}