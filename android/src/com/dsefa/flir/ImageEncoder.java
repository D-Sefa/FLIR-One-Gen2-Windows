package com.dsefa.flir;
import android.graphics.Bitmap;
import java.io.ByteArrayOutputStream;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** JPEG encoding never holds up the thermal display worker. One pending image maximum. */
final class ImageEncoder implements AutoCloseable {
    private final ThreadPoolExecutor worker=new ThreadPoolExecutor(1,1,10,TimeUnit.SECONDS,new ArrayBlockingQueue<>(1),r->{Thread t=new Thread(r,"image-encoder");t.setDaemon(true);return t;},new ThreadPoolExecutor.DiscardPolicy());
    private final Consumer<String> error;
    ImageEncoder(Consumer<String> error){this.error=error;worker.allowCoreThreadTimeOut(true);}
    void submit(ImageRecorder recorder,int[] colors,long stamp){if(worker.isShutdown())return;worker.execute(()->{
        Bitmap bitmap=null;try{bitmap=Bitmap.createBitmap(colors,160,120,Bitmap.Config.ARGB_8888);ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            if(!bitmap.compress(Bitmap.CompressFormat.JPEG,92,bytes))throw new IllegalStateException("JPEG encode failed");recorder.offer(bytes.toByteArray(),stamp);
        }catch(Exception e){error.accept("Image recording: "+e.getMessage());}finally{if(bitmap!=null)bitmap.recycle();}
    });}
    public void close(){worker.shutdownNow();}
}
