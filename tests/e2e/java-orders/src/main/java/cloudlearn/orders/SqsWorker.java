package cloudlearn.orders;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.*;

/**
 * Background worker thread that polls the OrderProcessing queue and "processes"
 * each message (logs it; in a real app would update order state, ship, etc.).
 *
 * Demonstrates the worker side of the queue surface. Console-pass + API-pass
 * tests assert that messages produced by POST /orders are drained by this
 * worker within a few seconds.
 */
@Component
public class SqsWorker {

    private static final Logger log = LoggerFactory.getLogger(SqsWorker.class);

    private final SqsClient sqs;
    @Value("${cloudlearn.queue-name}") private String queueName;
    private volatile boolean running = true;
    private Thread thread;

    public SqsWorker(SqsClient sqs) { this.sqs = sqs; }

    @PostConstruct
    public void start() {
        thread = new Thread(this::loop, "sqs-worker");
        thread.setDaemon(true);
        thread.start();
        log.info("SqsWorker started (queue={})", queueName);
    }

    @PreDestroy
    public void stop() {
        running = false;
        if (thread != null) thread.interrupt();
    }

    private void loop() {
        // Ensure queue exists once, then poll.
        String qurl;
        try {
            qurl = sqs.getQueueUrl(b -> b.queueName(queueName)).queueUrl();
        } catch (QueueDoesNotExistException e) {
            sqs.createQueue(b -> b.queueName(queueName));
            qurl = sqs.getQueueUrl(b -> b.queueName(queueName)).queueUrl();
        }

        while (running) {
            try {
                var resp = sqs.receiveMessage(ReceiveMessageRequest.builder()
                        .queueUrl(qurl)
                        .maxNumberOfMessages(10)
                        .waitTimeSeconds(2)
                        .build());
                for (Message m : resp.messages()) {
                    log.info("Worker processing message: {}", m.body());
                    sqs.deleteMessage(DeleteMessageRequest.builder()
                            .queueUrl(qurl)
                            .receiptHandle(m.receiptHandle())
                            .build());
                }
            } catch (Exception e) {
                if (running) {
                    log.warn("Worker poll error (will retry): {}", e.getMessage());
                    try { Thread.sleep(2000); } catch (InterruptedException ie) { break; }
                }
            }
        }
    }
}
