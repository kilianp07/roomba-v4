/*
 * mqtt_bridge.c - TLS+MQTT bridge for iRobot Roomba v4 protocol
 *
 * Handles the TLS connection (with RSA-PSS sigalgs workaround) and MQTT
 * protocol, exposing a simple line-based protocol over a Unix domain socket.
 *
 * Protocol (over Unix socket):
 *   Client -> Bridge:
 *     CONNECT <ip> <blid> <password>
 *     SUB <topic>
 *     PUB <topic> <payload>
 *     PING
 *     DISCONNECT
 *
 *   Bridge -> Client:
 *     OK CONNECTED
 *     OK SUBSCRIBED <topic>
 *     OK PUBLISHED
 *     MSG <topic> <payload_json>
 *     ERR <message>
 *     PONG
 *
 * Usage: mqtt_bridge [socket_path]
 *   Default socket: /tmp/roomba_bridge.sock
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <poll.h>
#include <fcntl.h>
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <openssl/conf.h>

#define MAX_BUF 65536
#define MAX_LINE 8192

static volatile int g_running = 1;
static SSL *g_ssl = NULL;
static SSL_CTX *g_ctx = NULL;
static int g_sock = -1;
static int g_packet_id = 1;

void sig_handler(int s) { (void)s; g_running = 0; }

/* -- MQTT helpers -- */

int encode_rem(unsigned char *b, int l) {
    int i = 0;
    do { unsigned char v = l % 128; l /= 128; if (l > 0) v |= 0x80; b[i++] = v; } while (l > 0);
    return i;
}

int do_connect(const char *ip, const char *blid, const char *pass) {
    /* Wake robot via UDP */
    int udp = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in ua = {.sin_family = AF_INET, .sin_port = htons(5678)};
    inet_pton(AF_INET, ip, &ua.sin_addr);
    sendto(udp, "irobotmcs", 9, 0, (struct sockaddr*)&ua, sizeof(ua));
    close(udp);
    usleep(500000);

    /* TLS */
    if (!g_ctx) {
        OPENSSL_init_ssl(OPENSSL_INIT_LOAD_CONFIG, NULL);
        g_ctx = SSL_CTX_new(TLS_client_method());
        SSL_CTX_set_verify(g_ctx, SSL_VERIFY_NONE, NULL);
        SSL_CTX_set_security_level(g_ctx, 0);
        SSL_CTX_set_min_proto_version(g_ctx, TLS1_2_VERSION);
        SSL_CTX_set_max_proto_version(g_ctx, TLS1_2_VERSION);
        SSL_CTX_set_cipher_list(g_ctx, "ECDHE-RSA-AES256-GCM-SHA384:DEFAULT");
        SSL_CTX_set_options(g_ctx, SSL_OP_LEGACY_SERVER_CONNECT);
        SSL_CTX_set1_sigalgs_list(g_ctx, "RSA+SHA256:RSA+SHA384:RSA+SHA512");
    }

    g_sock = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(8883)};
    inet_pton(AF_INET, ip, &addr.sin_addr);
    struct timeval tv = {5, 0};
    setsockopt(g_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    if (connect(g_sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) return -1;

    g_ssl = SSL_new(g_ctx);
    SSL_set_fd(g_ssl, g_sock);
    if (SSL_connect(g_ssl) <= 0) { SSL_free(g_ssl); g_ssl = NULL; close(g_sock); return -2; }

    /* MQTT CONNECT */
    unsigned char p[512];
    int ci = strlen(blid), u = strlen(blid), pw = strlen(pass);
    int rem = 10 + 2 + ci + 2 + u + 2 + pw, pos = 0;
    p[pos++] = 0x10; pos += encode_rem(p + pos, rem);
    p[pos++] = 0; p[pos++] = 4; memcpy(p + pos, "MQTT", 4); pos += 4;
    p[pos++] = 4; p[pos++] = 0xC2; p[pos++] = 0; p[pos++] = 30;
    p[pos++] = ci >> 8; p[pos++] = ci & 0xFF; memcpy(p + pos, blid, ci); pos += ci;
    p[pos++] = u >> 8; p[pos++] = u & 0xFF; memcpy(p + pos, blid, u); pos += u;
    p[pos++] = pw >> 8; p[pos++] = pw & 0xFF; memcpy(p + pos, pass, pw); pos += pw;
    SSL_write(g_ssl, p, pos);

    unsigned char resp[256];
    int n = SSL_read(g_ssl, resp, sizeof(resp));
    if (n < 4 || resp[0] != 0x20 || resp[3] != 0) return -3;

    return 0;
}

void do_subscribe(const char *topic) {
    if (!g_ssl) return;
    unsigned char p[512]; int tl = strlen(topic), rem = 2 + 2 + tl + 1, pos = 0;
    int pid = g_packet_id++;
    p[pos++] = 0x82; pos += encode_rem(p + pos, rem);
    p[pos++] = pid >> 8; p[pos++] = pid & 0xFF;
    p[pos++] = tl >> 8; p[pos++] = tl & 0xFF; memcpy(p + pos, topic, tl); pos += tl;
    p[pos++] = 1;
    SSL_write(g_ssl, p, pos);
}

void do_publish(const char *topic, const char *payload, int qos) {
    if (!g_ssl) return;
    unsigned char p[MAX_BUF]; int tl = strlen(topic), pl = strlen(payload);
    int rem = 2 + tl + pl; if (qos > 0) rem += 2; int pos = 0;
    p[pos++] = 0x30 | (qos << 1); pos += encode_rem(p + pos, rem);
    p[pos++] = tl >> 8; p[pos++] = tl & 0xFF; memcpy(p + pos, topic, tl); pos += tl;
    if (qos > 0) { int pid = g_packet_id++; p[pos++] = pid >> 8; p[pos++] = pid & 0xFF; }
    memcpy(p + pos, payload, pl); pos += pl;
    SSL_write(g_ssl, p, pos);
}

void do_ping(void) {
    if (!g_ssl) return;
    unsigned char p[] = {0xC0, 0x00};
    SSL_write(g_ssl, p, 2);
}

void do_disconnect(void) {
    if (g_ssl) {
        unsigned char dc[] = {0xE0, 0x00};
        SSL_write(g_ssl, dc, 2);
        SSL_shutdown(g_ssl);
        SSL_free(g_ssl);
        g_ssl = NULL;
    }
    if (g_sock >= 0) { close(g_sock); g_sock = -1; }
}

/* Read one MQTT packet from SSL and format as a line for the client */
/* Returns: 1 = got a message, 0 = other packet, -1 = no data/error */
int read_mqtt_packet(char *out, int out_sz) {
    if (!g_ssl) return -1;
    unsigned char buf[MAX_BUF];
    int n = SSL_read(g_ssl, buf, sizeof(buf) - 1);
    if (n <= 0) return -1;

    int pt = buf[0] & 0xF0;
    if (pt == 0x30) { /* PUBLISH */
        int pos = 1, rem = 0, shift = 0;
        do { rem |= (buf[pos] & 0x7F) << shift; shift += 7; } while (buf[pos++] & 0x80);
        int tl = (buf[pos] << 8) | buf[pos + 1]; pos += 2;
        char topic[512]; memcpy(topic, buf + pos, tl < 511 ? tl : 511); topic[tl < 511 ? tl : 511] = 0;
        pos += tl; int pl = rem - 2 - tl;
        int qos = (buf[0] >> 1) & 3;
        if (qos > 0) {
            unsigned char ack[4] = {0x40, 0x02, buf[pos], buf[pos + 1]};
            SSL_write(g_ssl, ack, 4);
            pos += 2; pl -= 2;
        }
        if (pl > 0) {
            buf[pos + pl] = 0;
            snprintf(out, out_sz, "MSG %s %.*s\n", topic, pl < 4000 ? pl : 4000, (char*)buf + pos);
        } else {
            snprintf(out, out_sz, "MSG %s {}\n", topic);
        }
        return 1;
    } else if (pt == 0x90) { /* SUBACK */
        snprintf(out, out_sz, "OK SUBSCRIBED\n");
        return 0;
    } else if (pt == 0x40) { /* PUBACK */
        snprintf(out, out_sz, "OK PUBLISHED\n");
        return 0;
    } else if (pt == 0xD0) { /* PINGRESP */
        snprintf(out, out_sz, "PONG\n");
        return 0;
    }
    return 0;
}

/* -- Main loop -- */

int main(int argc, char *argv[]) {
    signal(SIGPIPE, SIG_IGN);
    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);

    const char *sock_path = argc > 1 ? argv[1] : "/tmp/roomba_bridge.sock";

    /* Create Unix socket */
    unlink(sock_path);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un sa = {.sun_family = AF_UNIX};
    strncpy(sa.sun_path, sock_path, sizeof(sa.sun_path) - 1);
    bind(srv, (struct sockaddr*)&sa, sizeof(sa));
    listen(srv, 2);

    /* Non-blocking */
    fcntl(srv, F_SETFL, O_NONBLOCK);

    fprintf(stderr, "mqtt_bridge: listening on %s\n", sock_path);

    int client_fd = -1;
    char line_buf[MAX_LINE];
    int line_pos = 0;
    time_t last_ping = time(NULL);

    while (g_running) {
        struct pollfd fds[3];
        int nfds = 0;

        fds[nfds].fd = srv; fds[nfds].events = POLLIN; nfds++;
        if (client_fd >= 0) { fds[nfds].fd = client_fd; fds[nfds].events = POLLIN; nfds++; }

        int ret = poll(fds, nfds, 1000); /* 1 second timeout */

        /* Keepalive */
        if (g_ssl && time(NULL) - last_ping >= 20) {
            do_ping();
            last_ping = time(NULL);
        }

        /* Check for MQTT data */
        if (g_ssl && client_fd >= 0) {
            char msg[MAX_BUF];
            int r = read_mqtt_packet(msg, sizeof(msg));
            if (r >= 0 && strlen(msg) > 0) {
                write(client_fd, msg, strlen(msg));
            }
        }

        if (ret <= 0) continue;

        /* Accept new client */
        if (fds[0].revents & POLLIN) {
            int new_fd = accept(srv, NULL, NULL);
            if (new_fd >= 0) {
                if (client_fd >= 0) close(client_fd);
                client_fd = new_fd;
                line_pos = 0;
                fprintf(stderr, "mqtt_bridge: client connected\n");
            }
        }

        /* Read from client */
        if (client_fd >= 0 && nfds > 1 && fds[1].revents & POLLIN) {
            char tmp[4096];
            int n = read(client_fd, tmp, sizeof(tmp));
            if (n <= 0) {
                close(client_fd); client_fd = -1; line_pos = 0;
                fprintf(stderr, "mqtt_bridge: client disconnected\n");
                continue;
            }

            for (int i = 0; i < n; i++) {
                if (tmp[i] == '\n' || line_pos >= MAX_LINE - 1) {
                    line_buf[line_pos] = 0;
                    line_pos = 0;

                    /* Parse command */
                    char *cmd = line_buf;
                    char resp[MAX_BUF];

                    if (strncmp(cmd, "CONNECT ", 8) == 0) {
                        char ip[64], blid[128], pass[128];
                        if (sscanf(cmd + 8, "%63s %127s %127s", ip, blid, pass) == 3) {
                            int rc = do_connect(ip, blid, pass);
                            if (rc == 0) {
                                snprintf(resp, sizeof(resp), "OK CONNECTED\n");
                                last_ping = time(NULL);
                            } else {
                                snprintf(resp, sizeof(resp), "ERR connect_failed rc=%d\n", rc);
                            }
                        } else {
                            snprintf(resp, sizeof(resp), "ERR usage: CONNECT ip blid password\n");
                        }
                        write(client_fd, resp, strlen(resp));
                    } else if (strncmp(cmd, "SUB ", 4) == 0) {
                        do_subscribe(cmd + 4);
                        snprintf(resp, sizeof(resp), "OK SUB %s\n", cmd + 4);
                        write(client_fd, resp, strlen(resp));
                    } else if (strncmp(cmd, "PUB ", 4) == 0) {
                        /* PUB topic payload */
                        char topic[512], payload[MAX_LINE];
                        char *sp = strchr(cmd + 4, ' ');
                        if (sp) {
                            *sp = 0;
                            strncpy(topic, cmd + 4, sizeof(topic) - 1);
                            topic[sizeof(topic) - 1] = 0;
                            strncpy(payload, sp + 1, sizeof(payload) - 1);
                            payload[sizeof(payload) - 1] = 0;
                            do_publish(topic, payload, 0);
                            snprintf(resp, sizeof(resp), "OK PUB\n");
                        } else {
                            snprintf(resp, sizeof(resp), "ERR usage: PUB topic payload\n");
                        }
                        write(client_fd, resp, strlen(resp));
                    } else if (strcmp(cmd, "PING") == 0) {
                        do_ping();
                        snprintf(resp, sizeof(resp), "PONG\n");
                        write(client_fd, resp, strlen(resp));
                    } else if (strcmp(cmd, "DISCONNECT") == 0) {
                        do_disconnect();
                        snprintf(resp, sizeof(resp), "OK DISCONNECTED\n");
                        write(client_fd, resp, strlen(resp));
                    } else {
                        snprintf(resp, sizeof(resp), "ERR unknown_command\n");
                        write(client_fd, resp, strlen(resp));
                    }
                } else {
                    line_buf[line_pos++] = tmp[i];
                }
            }
        }
    }

    do_disconnect();
    if (client_fd >= 0) close(client_fd);
    close(srv);
    unlink(sock_path);
    if (g_ctx) SSL_CTX_free(g_ctx);
    fprintf(stderr, "mqtt_bridge: shutdown\n");
    return 0;
}
