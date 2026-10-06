package com.dsefa.flir;
import java.io.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Bounded disk queue: USB never waits for storage. */
public final class RawRecorder implements AutoCloseable {
    private final ArrayBlockingQueue<RawArchive.Sample> queue=new ArrayBlockingQueue<>(64);
    private volatile boolean running=true;
    private final CountDownLatch completed=new CountDownLatch(1);
    public RawRecorder(File file,Consumer<String> error)throws IOException{
        if(!file.createNewFile())throw new IOException("Archive already exists; refusing to overwrite");
        new Thread(()->{
            try(RawArchive.Writer writer=new RawArchive.Writer(new FileOutputStream(file))){
                while(running||!queue.isEmpty()){
                    RawArchive.Sample s=queue.poll(100,TimeUnit.MILLISECONDS);
                    if(s!=null)writer.write(s.timestamp,s.raw);
                }
            }catch(Exception e){running=false;error.accept("Recording: "+e.getMessage());}
            finally{completed.countDown();}
        },"FLIR RAW writer").start();
    }
    public synchronized boolean offer(int[] raw,long timestamp){if(!running)return false;
        RawArchive.Sample s=new RawArchive.Sample();s.raw=raw;s.timestamp=timestamp;return queue.offer(s);}
    public synchronized void close(){running=false;}
    public boolean complete(){return completed.getCount()==0;}
    public boolean awaitComplete(long milliseconds)throws InterruptedException{return completed.await(milliseconds,TimeUnit.MILLISECONDS);}
}
